"""Sandboxed execution helpers for plans and recipes."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from magent.command_policy import command_policy, run_policy_checked_command
from magent.workbench_domains.plans import show_plan
from magent.workbench_store import now_iso

# One vocabulary for every caller. Three different sets used to coexist:
# SANDBOX_MODES here, {"shared","worktree","sandbox"} in graph_workspace, and
# all four in agraph/execute.py — so `isolation: container` validated and then
# died at runtime with RT014.
SANDBOX_MODES = {"shared", "worktree", "copy", "sandbox", "container"}

# `sandbox` is the graph-side name for `copy`.
MODE_ALIASES = {"sandbox": "copy"}


def normalize_mode(mode: str) -> str:
    """Canonical mode name, or "" when the mode is unknown."""
    normalized = (mode or "").strip().lower()
    normalized = MODE_ALIASES.get(normalized, normalized)
    return normalized if normalized in {"shared", "worktree", "copy", "container"} else ""


@contextmanager
def graph_workspace(root: Path, mode: str):
    """Provision an AGS node workspace without silently weakening isolation."""
    normalized = normalize_mode(mode)
    if not normalized:
        raise RuntimeError(f"RT014 unsupported isolation mode {mode!r}")
    if normalized == "shared":
        yield root
        return
    if normalized == "container":
        raise RuntimeError("RT014 container-isolated agent sessions are not available")
    if normalized == "worktree":
        if not shutil.which("git"):
            raise RuntimeError("RT014 git is required for worktree isolation")
        probe = _run(root, ["git", "rev-parse", "--show-toplevel"], timeout=30)
        if not probe.get("ok"):
            raise RuntimeError("RT014 worktree isolation requires a Git repository")
        target = Path(tempfile.mkdtemp(prefix="magent-agraph-worktree-"))
        result = _run(root, ["git", "worktree", "add", "--detach", str(target), "HEAD"], timeout=120)
        if not result.get("ok"):
            shutil.rmtree(target, ignore_errors=True)
            raise RuntimeError(f"RT014 could not create worktree: {result.get('stderr', result.get('error', 'unknown error'))}")
        try:
            yield target
        finally:
            _run(root, ["git", "worktree", "remove", "--force", str(target)], timeout=120)
            shutil.rmtree(target, ignore_errors=True)
        return
    if normalized == "copy":
        target = Path(tempfile.mkdtemp(prefix="magent-agraph-sandbox-"))
        # .git is copied: plans apply patches with `git apply`, which cannot
        # work in a tree that has no repository.
        ignore = shutil.ignore_patterns(".venv", "node_modules", "__pycache__", ".pytest_cache")
        shutil.copytree(root, target, dirs_exist_ok=True, ignore=ignore)
        try:
            yield target
        finally:
            shutil.rmtree(target, ignore_errors=True)
        return
    raise RuntimeError(f"RT014 unsupported isolation mode {mode!r}")


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
        self.is_worktree = False
        if self.mode == "worktree":
            if not (self.root / ".git").exists() or not shutil.which("git"):
                raise RuntimeError(
                    "worktree isolation requires a git repository and the git binary"
                )
            target = Path(tempfile.mkdtemp(prefix="magent-worktree-"))
            check = _run(self.root, ["git", "worktree", "add", "--detach", str(target), "HEAD"], timeout=120)
            if not check["ok"]:
                shutil.rmtree(target, ignore_errors=True)
                # Degrading to a plain copy meant the caller believed it had a
                # worktree, and __exit__ then ran `git worktree remove` on a
                # path git had never registered.
                raise RuntimeError(
                    f"could not create worktree: {check.get('stderr') or check.get('error') or 'unknown error'}"
                )
            self.path = target
            self.is_worktree = True
            return target

        target = Path(tempfile.mkdtemp(prefix=f"magent-{self.mode}-"))
        # .git is copied: plan operations apply patches with `git apply`.
        ignore = shutil.ignore_patterns(".venv", "node_modules", "__pycache__", ".pytest_cache")
        shutil.copytree(self.root, target, dirs_exist_ok=True, ignore=ignore)
        self.path = target
        return target

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.keep or self.path is None:
            return
        if getattr(self, "is_worktree", False):
            _run(self.root, ["git", "worktree", "remove", "--force", str(self.path)], timeout=120)
        shutil.rmtree(self.path, ignore_errors=True)


def _execute_local_plan(plan: dict[str, Any], workspace: Path, *, run_checks: bool) -> dict[str, Any]:
    results = []
    for op in plan.get("operations", []):
        if op.get("type") == "patch" and op.get("path"):
            # The stored plan supplies this path and it may be absolute or
            # `../`-relative; the shell branch below is policy-checked but this
            # one applied whatever it was given.
            patch_path = (workspace / str(op["path"])).resolve(strict=False)
            try:
                patch_path.relative_to(workspace.resolve(strict=False))
            except ValueError:
                results.append(
                    {
                        "ok": False,
                        "error": f"Patch path escapes the workspace: {op['path']}",
                        "operation": op,
                    }
                )
                continue
            results.append({**_run(workspace, ["git", "apply", str(patch_path)], timeout=120), "operation": op})
        elif op.get("type") == "shell" and op.get("command"):
            results.append({**_run_command(workspace, op["command"], timeout=120), "operation": op})
    if run_checks:
        for command in plan.get("checks", []):
            results.append({**_run_command(workspace, command, timeout=180), "check": command})
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
    policies = [command_policy(_command_text(command)) for command in commands]
    if any(policy.get("blocked") for policy in policies):
        return {
            "ok": False,
            "workspace": str(workspace),
            "image": image,
            "results": [{**policy, "error": "Blocked by MagAgent command policy"} for policy in policies],
        }
    script = " && ".join(_command_text(command) for command in commands) or "pwd"
    # The joined script is what actually executes, so it is classified too:
    # classifying the pieces individually missed what the join creates.
    joined_policy = command_policy(script)
    if joined_policy.get("blocked"):
        return {
            "ok": False,
            "workspace": str(workspace),
            "image": image,
            "results": [{**joined_policy, "error": "Blocked by MagAgent command policy"}],
        }
    cmd = [
        "docker",
        "run",
        "--rm",
        # Isolation that actually isolates: no network, no root, bounded
        # resources, and a read-only root filesystem outside /workspace.
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "1000:1000",
        "--memory",
        "2g",
        "--pids-limit",
        "512",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
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
    return {
        "ok": result["ok"],
        "workspace": str(workspace),
        "image": image,
        "command": shlex.join(cmd),
        "command_policies": policies,
        "results": [result],
    }


def _plan_commands(plan: dict[str, Any], *, run_checks: bool) -> list[Any]:
    commands = []
    for op in plan.get("operations", []):
        if op.get("type") == "shell" and op.get("command"):
            commands.append(op["command"])
    if run_checks:
        commands.extend(str(item) for item in plan.get("checks", []) if str(item).strip())
    return commands


def _command_text(command: Any) -> str:
    if isinstance(command, str):
        return command
    if isinstance(command, dict):
        if "argv" in command:
            return shlex.join(str(item) for item in command.get("argv") or [])
        return str(command.get("command") or "")
    if isinstance(command, (list, tuple)):
        return shlex.join(str(item) for item in command)
    return str(command)


def _run_command(cwd: Path, command: Any, *, timeout: int) -> dict[str, Any]:
    result = run_policy_checked_command(command, cwd=cwd, timeout=timeout)
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


# ─────────────────────────────────────────────
# Sandboxed shell execution (roadmap feature #3)
# ─────────────────────────────────────────────

SHELL_SANDBOX_PROFILES = {"off", "bubblewrap", "docker"}


def shell_sandbox_available(profile: str) -> bool:
    """Whether the requested isolation profile can actually run here."""
    normalized = (profile or "off").strip().lower()
    if normalized == "off":
        return True
    if normalized == "bubblewrap":
        return shutil.which("bwrap") is not None
    if normalized == "docker":
        return shutil.which("docker") is not None
    return False


def wrap_shell_command(
    command: str,
    *,
    profile: str,
    cwd: str | Path,
    network: bool = False,
    image: str = "python:3.12-slim",
) -> list[str] | None:
    """Return argv that runs `command` under `profile`, or None for no wrapping.

    Defence in depth for `run_shell`: the classifier decides *whether* a command
    may run, and this decides *what it can reach* if it does. Given how many
    ways the old classifier could be talked into a silent execution, a command
    that cannot see beyond the project directory is worth having even when the
    tier says it is fine.
    """
    normalized = (profile or "off").strip().lower()
    if normalized not in SHELL_SANDBOX_PROFILES:
        raise ValueError(f"Unknown shell sandbox profile: {profile!r}")
    if normalized == "off":
        return None
    if not shell_sandbox_available(normalized):
        raise RuntimeError(f"Shell sandbox profile {normalized!r} is not available on this machine")

    workdir = str(Path(cwd).resolve())

    if normalized == "bubblewrap":
        argv = [
            "bwrap",
            "--die-with-parent",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            # Read-only system, writable project only.
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--bind", workdir, workdir,
            "--chdir", workdir,
        ]
        if not network:
            argv.append("--unshare-net")
        return [*argv, "sh", "-lc", command]

    return [
        "docker",
        "run",
        "--rm",
        "-i",
        *([] if network else ["--network", "none"]),
        "--user",
        f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "1000:1000",
        "--memory", "2g",
        "--pids-limit", "512",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{workdir}:{workdir}",
        "-w", workdir,
        image,
        "sh",
        "-lc",
        command,
    ]
