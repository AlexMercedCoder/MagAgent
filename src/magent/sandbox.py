"""Sandboxed execution helpers for plans and recipes."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from magent.command_policy import run_policy_checked_shell
from magent.workbench_domains.plans import show_plan
from magent.workbench_store import now_iso

SANDBOX_MODES = {"worktree", "copy", "container"}


def execute_plan_sandbox(
    store: Any,
    plan_id: str,
    *,
    mode: str = "worktree",
    run_checks: bool = False,
    keep: bool = False,
    image: str = "python:3.12",
) -> dict[str, Any]:
    """Execute a saved plan in an isolated worktree, copy, or container workspace."""
    normalized = mode.strip().lower()
    if normalized not in SANDBOX_MODES:
        return {"ok": False, "error": f"Unknown sandbox mode: {mode}", "known": sorted(SANDBOX_MODES)}
    plan = show_plan(store, plan_id)
    if not plan:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}
    root = Path(plan.get("root", ".")).resolve()
    with _sandbox_workspace(root, normalized, keep=keep) as workspace:
        if normalized == "container":
            result = _execute_container_plan(plan, workspace, run_checks=run_checks, image=image)
        else:
            result = _execute_local_plan(plan, workspace, run_checks=run_checks)
        record = store.append(
            "sandbox_runs",
            {
                "plan_id": plan_id,
                "mode": normalized,
                "root": str(root),
                "workspace": str(workspace),
                "kept": keep,
                "result": result,
                "status": "passed" if result.get("ok") else "failed",
                "completed_at": now_iso(),
            },
        )
        return {"ok": result.get("ok", False), "sandbox": record, "result": result}


def sandbox_plan_preview(store: Any, plan_id: str, mode: str = "worktree") -> dict[str, Any]:
    """Describe what sandbox execution would do without running operations."""
    plan = show_plan(store, plan_id)
    if not plan:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}
    commands = _plan_commands(plan, run_checks=True)
    return {
        "ok": True,
        "plan_id": plan_id,
        "mode": mode,
        "root": plan.get("root", ""),
        "operations": plan.get("operations", []),
        "checks": plan.get("checks", []),
        "commands": commands,
    }


def list_sandbox_runs(store: Any, limit: int = 20) -> list[dict[str, Any]]:
    """List recent sandbox executions."""
    return list(reversed(store.read("sandbox_runs", [])))[0:limit]


class _sandbox_workspace:
    def __init__(self, root: Path, mode: str, *, keep: bool) -> None:
        self.root = root
        self.mode = mode
        self.keep = keep
        self.path: Path | None = None

    def __enter__(self) -> Path:
        if self.mode == "worktree" and (self.root / ".git").exists() and shutil.which("git"):
            target = Path(tempfile.mkdtemp(prefix="magent-worktree-"))
            check = _run(self.root, ["git", "worktree", "add", "--detach", str(target), "HEAD"], timeout=120)
            if check["ok"]:
                self.path = target
                return target
            shutil.rmtree(target, ignore_errors=True)
        target = Path(tempfile.mkdtemp(prefix=f"magent-{self.mode}-"))
        ignore = shutil.ignore_patterns(".git", ".venv", "node_modules", "__pycache__", ".pytest_cache")
        shutil.copytree(self.root, target, dirs_exist_ok=True, ignore=ignore)
        self.path = target
        return target

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.keep or self.path is None:
            return
        if self.mode == "worktree" and (self.root / ".git").exists() and shutil.which("git"):
            _run(self.root, ["git", "worktree", "remove", "--force", str(self.path)], timeout=120)
        shutil.rmtree(self.path, ignore_errors=True)


def _execute_local_plan(plan: dict[str, Any], workspace: Path, *, run_checks: bool) -> dict[str, Any]:
    results = []
    for op in plan.get("operations", []):
        if op.get("type") == "patch" and op.get("path"):
            results.append({**_run(workspace, ["git", "apply", str(op["path"])], timeout=120), "operation": op})
        elif op.get("type") == "shell" and op.get("command"):
            results.append({**_run_shell(workspace, op["command"], timeout=120), "operation": op})
    if run_checks:
        for command in plan.get("checks", []):
            results.append({**_run_shell(workspace, command, timeout=180), "check": command})
    return {"ok": all(item.get("ok") for item in results), "workspace": str(workspace), "results": results}


def _execute_container_plan(
    plan: dict[str, Any],
    workspace: Path,
    *,
    run_checks: bool,
    image: str,
) -> dict[str, Any]:
    if not shutil.which("docker"):
        return {"ok": False, "error": "Docker is not available"}
    commands = _plan_commands(plan, run_checks=run_checks)
    script = " && ".join(commands) or "pwd"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace}:/workspace",
        "-w",
        "/workspace",
        image,
        "sh",
        "-lc",
        script,
    ]
    result = _run(Path.cwd(), cmd, timeout=600)
    return {"ok": result["ok"], "workspace": str(workspace), "image": image, "command": shlex.join(cmd), "results": [result]}


def _plan_commands(plan: dict[str, Any], *, run_checks: bool) -> list[str]:
    commands = []
    for op in plan.get("operations", []):
        if op.get("type") == "shell" and op.get("command"):
            commands.append(op["command"])
    if run_checks:
        commands.extend(str(item) for item in plan.get("checks", []) if str(item).strip())
    return commands


def _run_shell(cwd: Path, command: str, *, timeout: int) -> dict[str, Any]:
    result = run_policy_checked_shell(command, cwd=cwd, timeout=timeout)
    if "returncode" in result:
        result["stdout"] = str(result.get("stdout", ""))[-3000:]
        result["stderr"] = str(result.get("stderr", ""))[-3000:]
    return result


def _run(cwd: Path, cmd: list[str], *, timeout: int) -> dict[str, Any]:
    try:
        return _completed(
            shlex.join(cmd),
            subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout),
        )
    except Exception as e:
        return {"ok": False, "command": shlex.join(cmd), "error": str(e)}


def _completed(command: str, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "ok": result.returncode == 0,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout[-3000:],
        "stderr": result.stderr[-3000:],
    }


def sandbox_manifest() -> str:
    """Return a compact JSON description of supported sandbox modes."""
    return json.dumps(
        {
            "modes": {
                "worktree": "Use git worktree when available, falling back to a copied workspace.",
                "copy": "Copy the project to a temporary directory and run operations there.",
                "container": "Copy the project, then run commands inside Docker with the copy mounted.",
            }
        },
        indent=2,
    )
