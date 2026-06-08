"""Durable local workbench primitives for coding and productivity workflows."""

from __future__ import annotations

import ast
import csv
import difflib
import hashlib
import json
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import tomllib
import webbrowser
from collections import Counter
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from magent import workbench_store as _workbench_store
from magent.config import LOGS_DIR, USERS_DIR, user_memory_dir
from magent.project_scan import ignored_path, iter_project_files
from magent.tokens import estimate_tokens
from magent.workbench_store import now_iso

WORKBENCH_DIRNAME = _workbench_store.WORKBENCH_DIRNAME
MAX_CODE_INDEX_FILES = 1500
MAX_TEST_FILES = 500
MAX_TEST_SOURCE_FILES = 2000


class WorkbenchStore(_workbench_store.WorkbenchStore):
    """Compatibility wrapper honoring ``magent.workbench.USERS_DIR`` monkeypatches."""

    def __init__(self, username: str):
        _workbench_store.USERS_DIR = USERS_DIR
        super().__init__(username)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:60] or "item"


def task_add(store: WorkbenchStore, title: str, project: str = "", priority: str = "normal") -> dict:
    return store.append(
        "tasks",
        {
            "title": title,
            "project": project,
            "priority": priority,
            "status": "open",
            "notes": [],
        },
    )


def task_list(store: WorkbenchStore, status: str | None = None, project: str | None = None) -> list:
    tasks = store.read("tasks", [])
    if status:
        tasks = [task for task in tasks if task.get("status") == status]
    if project:
        tasks = [task for task in tasks if task.get("project") == project]
    return tasks


def artifact_add(store: WorkbenchStore, path: str, kind: str = "", title: str = "") -> dict:
    p = Path(path).expanduser().resolve(strict=False)
    return store.append(
        "artifacts",
        {
            "title": title or p.name,
            "path": str(p),
            "kind": kind or p.suffix.lstrip(".") or "file",
            "exists": p.exists(),
            "checksum": _file_sha256(p) if p.exists() and p.is_file() else "",
        },
    )


def artifact_show(store: WorkbenchStore, artifact_id: str) -> dict[str, Any] | None:
    return next((item for item in store.read("artifacts", []) if item.get("id") == artifact_id), None)


def artifact_checksum(store: WorkbenchStore, artifact_id: str) -> dict[str, Any]:
    item = artifact_show(store, artifact_id)
    if not item:
        return {"ok": False, "error": f"Artifact not found: {artifact_id}"}
    path = Path(item.get("path", "")).expanduser().resolve(strict=False)
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": f"Artifact file not found: {path}"}
    checksum = _file_sha256(path)
    store.update_item("artifacts", artifact_id, checksum=checksum, exists=True)
    return {"ok": True, "id": artifact_id, "path": str(path), "sha256": checksum}


def artifact_open_info(store: WorkbenchStore, artifact_id: str) -> dict[str, Any]:
    item = artifact_show(store, artifact_id)
    if not item:
        return {"ok": False, "error": f"Artifact not found: {artifact_id}"}
    path = Path(item.get("path", "")).expanduser().resolve(strict=False)
    return {"ok": path.exists(), "path": str(path), "kind": item.get("kind", ""), "exists": path.exists()}


def remember(store: WorkbenchStore, text: str, tags: list[str] | None = None) -> dict:
    return store.append("knowledge", {"text": text, "tags": tags or []})


def recall(store: WorkbenchStore, query: str, limit: int = 10) -> list[dict[str, Any]]:
    qwords = set(re.findall(r"\w+", query.lower()))
    scored = []
    for item in store.read("knowledge", []):
        text = item.get("text", "")
        tags = " ".join(item.get("tags", []))
        words = set(re.findall(r"\w+", f"{text} {tags}".lower()))
        score = len(qwords & words)
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def project_profile(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    files = []
    for name in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "README.md", "Makefile"):
        path = root_path / name
        if path.exists():
            files.append(name)
    project_cfg = load_project_config(root_path)
    commands = infer_project_commands(root_path)
    return {
        "root": str(root_path),
        "name": root_path.name,
        "detected_files": files,
        "commands": commands,
        "config": project_cfg,
        "updated_at": now_iso(),
    }


def save_project_profile(store: WorkbenchStore, root: str | Path) -> dict[str, Any]:
    profile = project_profile(root)
    profiles = store.read("projects", [])
    profiles = [item for item in profiles if item.get("root") != profile["root"]]
    profiles.append(profile)
    store.write("projects", profiles)
    return profile


def infer_project_commands(root: Path) -> list[str]:
    commands = []
    project_cfg = load_project_config(root)
    configured = project_cfg.get("commands", {})
    if isinstance(configured, dict):
        for value in configured.values():
            if isinstance(value, str):
                commands.append(value)
            elif isinstance(value, list):
                commands.extend(str(item) for item in value)
    if (root / "pyproject.toml").exists():
        commands.extend(["pytest -q", "ruff check src tests"])
        pyproject = _read_toml(root / "pyproject.toml")
        if pyproject.get("tool", {}).get("pytest"):
            commands.append("pytest")
        if (root / "uv.lock").exists():
            commands.extend(["uv run pytest -q", "uv run ruff check src tests"])
        if (root / "poetry.lock").exists():
            commands.extend(["poetry run pytest -q", "poetry run ruff check src tests"])
        if (root / "tox.ini").exists():
            commands.append("tox")
        if pyproject.get("tool", {}).get("tox"):
            commands.append("tox")
        if "nox" in pyproject.get("tool", {}):
            commands.append("nox")
    if (root / "package.json").exists():
        commands.extend(_package_json_commands(root / "package.json"))
    if (root / "deno.json").exists() or (root / "deno.jsonc").exists():
        commands.extend(["deno test", "deno lint"])
    if (root / "Cargo.toml").exists():
        commands.extend(["cargo test", "cargo clippy"])
    if (root / "go.mod").exists():
        commands.extend(["go test ./..."])
    commands.extend(_makefile_commands(root / "Makefile"))
    commands.extend(_justfile_commands(root / "justfile"))
    commands.extend(_justfile_commands(root / "Justfile"))
    try:
        from magent.playbook import playbook_commands

        commands.extend(playbook_commands(root))
    except Exception:
        pass
    return sorted(dict.fromkeys(command for command in commands if command.strip()))


COMMAND_ROLES = ("test", "test_related", "lint", "typecheck", "format", "build", "release")


def project_command_roles(root: str | Path) -> dict[str, str]:
    root_path = Path(root).resolve()
    project_cfg = load_project_config(root_path)
    configured = project_cfg.get("commands", {})
    roles: dict[str, str] = {}
    if isinstance(configured, dict):
        for role in COMMAND_ROLES:
            value = configured.get(role)
            if isinstance(value, str) and value.strip():
                roles[role] = value.strip()
            elif isinstance(value, list) and value:
                roles[role] = " && ".join(str(item) for item in value if str(item).strip())
    inferred = infer_project_commands(root_path)
    for command in inferred:
        lower = command.lower()
        if any(marker in lower for marker in ("pytest", "npm test", "pnpm test", "bun test", "deno test", "cargo test", "go test", "tox", "nox")):
            roles.setdefault("test", command)
        if any(marker in lower for marker in ("ruff", "eslint", "deno lint", "clippy")):
            roles.setdefault("lint", command)
        if "tsc" in lower or "typecheck" in lower:
            roles.setdefault("typecheck", command)
        if "build" in lower:
            roles.setdefault("build", command)
    return roles


def project_doctor(root: str | Path, store: WorkbenchStore | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    roles = project_command_roles(root_path)
    history = command_history(store, root_path) if store is not None else []
    role_status = {}
    for role in COMMAND_ROLES:
        command = roles.get(role, "")
        last = next((item for item in history if item.get("command") == command), None) if command else None
        role_status[role] = {
            "configured": bool(command),
            "command": command,
            "last_ok": last.get("ok") if last else None,
            "last_run": last.get("created_at") if last else "",
        }
    missing = [role for role, item in role_status.items() if not item["configured"]]
    return {
        "ok": "test" not in missing,
        "root": str(root_path),
        "roles": role_status,
        "missing": missing,
        "config": load_project_config(root_path),
    }


def load_project_config(root: str | Path) -> dict[str, Any]:
    path = Path(root).resolve() / ".magent" / "config.toml"
    return _read_toml(path)


def build_plan(root: str | Path, goal: str) -> str:
    profile = project_profile(root)
    root_path = Path(profile["root"])
    commands = profile.get("commands") or infer_project_commands(root_path) or ["git diff --stat"]
    diff_stat = _run_git(root_path, ["diff", "--stat"])
    focus = _plan_focus(goal, root_path)
    lines = [
        f"# Plan: {goal}",
        "",
        f"Project: `{profile['name']}`",
        f"Root: `{profile['root']}`",
        "",
        "## Project Signals",
        f"- Key files: {', '.join(profile.get('detected_files') or ['none detected'])}",
        f"- Configured commands: {len(commands)}",
        f"- Current diff: {'present' if diff_stat.strip() else 'none detected'}",
        "",
        "## Focus",
        *[f"- {item}" for item in focus],
        "",
        "## Suggested Steps",
        *_numbered_steps(goal),
        "",
        "## Likely Checks",
    ]
    lines.extend(f"- `{command}`" for command in commands)
    if diff_stat.strip():
        lines.extend(["", "## Current Diff Stat", "```", diff_stat.strip(), "```"])
    lines.extend(
        [
            "",
            "## Save / Run",
            "- Save this draft: `magent plan --save \"<goal>\"`",
            "- Save executable operations: `magent plan --save --executable \"<goal>\"`",
            "- Show saved plans: `magent plan-list`",
            "- Preview executable plan: `magent plan-preview <plan-id>`",
        ]
    )
    return "\n".join(lines)


def save_plan(store: WorkbenchStore, root: str | Path, goal: str) -> dict[str, Any]:
    profile = project_profile(root)
    checks = profile.get("commands") or ["git diff --stat"]
    return store.append(
        "plans",
        {
            "goal": goal,
            "root": profile["root"],
            "project": profile["name"],
            "status": "draft",
            "steps": [
                "Inspect relevant files with outline/range reads.",
                "Make small patch-oriented edits.",
                "Run focused checks.",
                "Review the diff and update docs/tests.",
            ],
            "checks": checks,
            "plan_markdown": build_plan(root, goal),
        },
    )


def _plan_focus(goal: str, root: Path) -> list[str]:
    text = goal.lower()
    focus = []
    if any(word in text for word in ("test", "coverage", "failing", "pytest", "repair")):
        focus.append("Prioritize reproducing failures and running the narrowest related tests first.")
    if any(word in text for word in ("docs", "readme", "documentation")):
        focus.append("Check README and packaged docs so user-facing instructions stay current.")
    if any(word in text for word in ("release", "publish", "version")):
        focus.append("Run release readiness checks and verify version/changelog surfaces before publishing.")
    if any(word in text for word in ("ui", "ux", "cli", "prompt")):
        focus.append("Exercise the user-facing command path, not only lower-level helpers.")
    if any((root / name).exists() for name in ("pyproject.toml", "setup.py")):
        focus.append("Use Python project conventions and prefer existing pytest/ruff commands.")
    return focus or ["Inspect the current project shape, then choose the smallest safe implementation path."]


def _numbered_steps(goal: str) -> list[str]:
    text = goal.lower()
    steps = [
        "1. Inspect relevant files with `outline_file` and targeted range reads.",
        "2. Identify the narrowest code/docs/test surface that satisfies the goal.",
        "3. Make small patch-oriented edits.",
    ]
    if any(word in text for word in ("test", "coverage", "repair", "bug")):
        steps.append("4. Reproduce the issue or run focused related tests before broad validation.")
    elif any(word in text for word in ("docs", "readme", "documentation")):
        steps.append("4. Update repo-facing and packaged docs together.")
    else:
        steps.append("4. Run the narrowest relevant checks.")
    steps.extend(
        [
            "5. Review the diff for unintended changes.",
            "6. Record follow-ups, decisions, or artifacts in the workbench if useful.",
        ]
    )
    return steps


def list_plans(store: WorkbenchStore, status: str | None = None) -> list[dict[str, Any]]:
    plans = store.read("plans", [])
    if status:
        plans = [plan for plan in plans if plan.get("status") == status]
    return plans


def apply_plan(
    store: WorkbenchStore,
    plan_id: str,
    run_checks: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    plans = store.read("plans", [])
    plan = next((item for item in plans if item.get("id") == plan_id), None)
    if not plan:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "plan": plan,
            "summary": preview_plan(plan),
            "operations": plan.get("operations", []),
            "checks": plan.get("checks", []),
        }
    operation_results = []
    for op in plan.get("operations", []):
        if op.get("type") == "shell":
            result = _run_command(plan.get("root", "."), op.get("command", ""), timeout=120)
            operation_results.append({**result, "operation": op, "stdout_excerpt": result.get("stdout", "")[-1200:], "stderr_excerpt": result.get("stderr", "")[-1200:]})
        elif op.get("type") == "patch":
            patch_path = op.get("path", "")
            if patch_path:
                check = _run_git_result(plan.get("root", "."), ["apply", "--check", patch_path])
                if check.returncode != 0:
                    operation_results.append(
                        {
                            "operation": op,
                            "ok": False,
                            "stdout": check.stdout,
                            "stderr": check.stderr,
                        }
                    )
                    continue
                applied = _run_git_result(plan.get("root", "."), ["apply", patch_path])
                operation_results.append(
                    {
                        "operation": op,
                        "ok": applied.returncode == 0,
                        "stdout": applied.stdout,
                        "stderr": applied.stderr,
                        "stdout_excerpt": applied.stdout[-1200:],
                        "stderr_excerpt": applied.stderr[-1200:],
                    }
                )
    check_results = []
    if run_checks:
        for command in plan.get("checks", []):
            result = _run_command(plan.get("root", "."), command, timeout=120)
            check_results.append({**result, "stdout_excerpt": result.get("stdout", "")[-1200:], "stderr_excerpt": result.get("stderr", "")[-1200:]})
            record_command_result(
                store,
                plan.get("root", "."),
                command,
                check_results[-1].get("ok", False),
                source="plan-apply",
            )
    ok = all(item.get("ok", False) for item in operation_results) and all(
        item.get("ok", False) for item in check_results
    )
    updated = store.update_item(
        "plans",
        plan_id,
        status="applied" if ok else "failed",
        applied_at=now_iso(),
        operation_results=operation_results,
        check_results=check_results,
    )
    return {"ok": ok, "plan": updated, "operations": operation_results, "checks": check_results}


def show_plan(store: WorkbenchStore, plan_id: str) -> dict[str, Any] | None:
    return next((item for item in store.read("plans", []) if item.get("id") == plan_id), None)


def discard_plan(store: WorkbenchStore, plan_id: str) -> dict[str, Any]:
    item = show_plan(store, plan_id)
    if not item:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}
    updated = store.update_item("plans", plan_id, status="discarded", discarded_at=now_iso())
    return {"ok": True, "plan": updated}


def save_plan_run(store: WorkbenchStore, root: str | Path, goal: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    item = save_plan(store, root_path, goal)
    diff_stat = _run_git(root_path, ["diff", "--stat"])
    return store.update_item(
        "plans",
        item["id"],
        status="pending",
        mode="plan-run",
        diff_stat=diff_stat,
        review=review_summary(root_path),
    ) or item


def save_execution_plan(
    store: WorkbenchStore,
    root: str | Path,
    goal: str,
    commands: list[str] | None = None,
    include_diff: bool = True,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    item = save_plan(store, root_path, goal)
    operations = []
    if include_diff:
        diff = _run_git(root_path, ["diff"])
        if diff.strip():
            patch_dir = store.root / "plan_patches"
            patch_dir.mkdir(parents=True, exist_ok=True)
            patch_path = patch_dir / f"{item['id']}.patch"
            patch_path.write_text(diff, encoding="utf-8")
            operations.append({"type": "patch", "path": str(patch_path), "bytes": len(diff.encode())})
    for command in commands or []:
        operations.append({"type": "shell", "command": command})
    return store.update_item(
        "plans",
        item["id"],
        status="pending",
        mode="execution",
        operations=operations,
        preview=preview_plan({**item, "operations": operations}),
    ) or item


def preview_plan(plan: dict[str, Any]) -> str:
    lines = [
        f"# Plan Preview: {plan.get('goal', plan.get('id', 'plan'))}",
        "",
        f"- ID: `{plan.get('id', '')}`",
        f"- Status: `{plan.get('status', '')}`",
        f"- Root: `{plan.get('root', '')}`",
        "",
        "## Operations",
    ]
    operations = plan.get("operations") or []
    if not operations:
        lines.append("- No executable operations buffered.")
    for index, op in enumerate(operations, start=1):
        if op.get("type") == "shell":
            lines.append(f"{index}. Run `{op.get('command', '')}`")
        elif op.get("type") == "patch":
            lines.append(f"{index}. Apply patch `{op.get('path', '')}` ({op.get('bytes', 0)} bytes)")
        else:
            lines.append(f"{index}. {op}")
    return "\n".join(lines)


def review_diff(root: str | Path, base: str = "HEAD") -> list[dict[str, Any]]:
    diff = _run_git(root, ["diff", base, "--"])
    findings = []
    patterns = [
        (
            "P1",
            r"(?:api[_-]?key|secret|password|token)\s*[:=]",
            "Possible secret or credential in diff.",
        ),
        ("P2", r"(?:#|//)\s*(?:TODO|FIXME)\b", "New TODO/FIXME may need tracking."),
        ("P2", r"except Exception\s*:\s*pass", "Broad silent exception can hide failures."),
        ("P3", r"^\+\s*print\(", "Debug print added; verify it is intentional."),
        ("P2", r"subprocess\.run\([^)]*shell=True", "shell=True can expose command injection risk."),
        ("P2", r"eval\(|exec\(", "Dynamic code execution added; verify input cannot reach it."),
    ]
    for lineno, line in enumerate(diff.splitlines(), start=1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for priority, pattern, message in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append(
                    {
                        "priority": priority,
                        "category": _review_category(message),
                        "line": lineno,
                        "message": message,
                        "evidence": line[:160],
                    }
                )
    changed = _run_git(root, ["diff", "--name-only", base, "--"]).splitlines()
    src_changed = [name for name in changed if name.startswith("src/")]
    tests_changed = [name for name in changed if name.startswith("tests/") or "test" in Path(name).name]
    if src_changed and not tests_changed:
        findings.append(
            {
                "priority": "P2",
                "category": "tests",
                "line": 0,
                "message": "Source changed without matching test changes.",
                "evidence": ", ".join(src_changed[:5]),
            }
        )
    return findings


def review_summary(root: str | Path, base: str = "HEAD") -> dict[str, Any]:
    from magent.lsp import lsp_diagnostics

    findings = review_diff(root, base)
    diagnostics = lsp_diagnostics(root)
    for diagnostic in diagnostics.get("diagnostics", [])[:20]:
        findings.append(
            {
                "priority": "P1",
                "category": "diagnostics",
                "line": 0,
                "message": diagnostic.get("message", "Diagnostic failure"),
                "evidence": diagnostic.get("path", ""),
            }
        )
    categories = Counter(item.get("category", "general") for item in findings)
    files = _run_git(root, ["diff", "--name-only", base, "--"]).splitlines()
    file_groups = {
        file: {
            "related_tests": related_tests(root, file),
            "risk": _file_risk(file),
        }
        for file in files
    }
    return {
        "ok": not any(item.get("priority") in {"P0", "P1"} for item in findings),
        "base": base,
        "findings": findings,
        "categories": dict(categories),
        "changed_files": files,
        "files": file_groups,
        "diagnostics": diagnostics,
    }


def review_fails_threshold(findings: list[dict[str, Any]], threshold: str) -> bool:
    priorities = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    threshold_score = priorities.get(threshold.upper(), 1)
    return any(priorities.get(str(item.get("priority", "P3")).upper(), 3) <= threshold_score for item in findings)


def save_review(store: WorkbenchStore, root: str | Path, base: str = "HEAD") -> dict[str, Any]:
    summary = review_summary(root, base)
    return store.append(
        "reviews",
        {
            "root": str(Path(root).resolve()),
            "base": base,
            "summary": summary,
            "status": "open",
        },
    )


def review_show(store: WorkbenchStore, review_id: str) -> dict[str, Any] | None:
    return next((item for item in store.read("reviews", []) if item.get("id") == review_id), None)


def repo_graph(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    imports: dict[str, list[str]] = {}
    for path in root_path.rglob("*.py"):
        if _ignored(path):
            continue
        rel = path.relative_to(root_path).as_posix()
        found = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", line)
            if m:
                found.append(next(group for group in m.groups() if group))
        imports[rel] = sorted(set(found))
    return {"root": str(root_path), "python_imports": imports, "files": len(imports)}


def code_index(root: str | Path) -> dict[str, Any]:
    """Build a lightweight persistent code intelligence index."""
    root_path = Path(root).resolve()
    files = []
    symbols = []
    imports: dict[str, list[str]] = {}
    truncated = False
    for scanned, path in enumerate(
        _iter_project_files(root_path, suffixes={".py"}, limit=MAX_CODE_INDEX_FILES + 1),
        start=1,
    ):
        if scanned > MAX_CODE_INDEX_FILES:
            truncated = True
            break
        rel = path.relative_to(root_path).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        file_info = {"path": rel, "lines": len(text.splitlines()), "symbols": []}
        try:
            tree = ast.parse(text)
            file_imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    file_imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    file_imports.append(node.module)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    item = {
                        "name": node.name,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                        "path": rel,
                        "line": node.lineno,
                        "doc": ast.get_docstring(node) or "",
                    }
                    symbols.append(item)
                    file_info["symbols"].append(item)
            imports[rel] = sorted(set(file_imports))
        except SyntaxError:
            imports[rel] = []
        files.append(file_info)
    return {
        "root": str(root_path),
        "files": files,
        "symbols": symbols,
        "imports": imports,
        "test_map": test_map(root_path),
        "updated_at": now_iso(),
        "limits": {
            "max_files": MAX_CODE_INDEX_FILES,
            "truncated": truncated,
        },
    }


def save_code_index(store: WorkbenchStore, root: str | Path) -> dict[str, Any]:
    index = code_index(root)
    indexes = store.read("code_indexes", [])
    indexes = [item for item in indexes if item.get("root") != index["root"]]
    indexes.append(index)
    store.write("code_indexes", indexes)
    return index


def search_symbols(store: WorkbenchStore, query: str, root: str | Path | None = None) -> list[dict[str, Any]]:
    indexes = store.read("code_indexes", [])
    if root:
        root_str = str(Path(root).resolve())
        indexes = [item for item in indexes if item.get("root") == root_str]
    q = query.lower()
    matches = []
    for index in indexes:
        for symbol in index.get("symbols", []):
            haystack = f"{symbol.get('name', '')} {symbol.get('path', '')} {symbol.get('doc', '')}".lower()
            if q in haystack:
                matches.append({**symbol, "root": index.get("root")})
    return matches


def related_code(store: WorkbenchStore, root: str | Path, file: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    root_str = str(root_path)
    indexes = [item for item in store.read("code_indexes", []) if item.get("root") == root_str]
    index = indexes[-1] if indexes else code_index(root_path)
    rel = _project_relative_path(root_path, file)
    tests = index.get("test_map", {}).get(rel, [])
    import_peers = [
        path
        for path, imports in index.get("imports", {}).items()
        if path != rel and any(part in " ".join(imports) for part in Path(rel).stem.split("_"))
    ]
    return {"root": root_str, "file": rel, "tests": tests, "related": sorted(set(import_peers + tests))}


def test_map(root: str | Path) -> dict[str, list[str]]:
    root_path = Path(root).resolve()
    test_patterns = ("test_*.py", "*_test.py", "*.test.js", "*.test.ts", "*_test.go", "*_test.rs")
    tests = []
    seen_tests = set()
    for pattern in test_patterns:
        for path in root_path.rglob(pattern):
            if _ignored(path) or path in seen_tests:
                continue
            tests.append(path)
            seen_tests.add(path)
            if len(tests) >= MAX_TEST_FILES:
                break
        if len(tests) >= MAX_TEST_FILES:
            break
    tests_with_text = [(test, _read_text_safe(test)) for test in tests]
    mapping: dict[str, list[str]] = {}
    source_suffixes = {".py", ".js", ".ts", ".go", ".rs"}
    for source in _iter_project_files(root_path, suffixes=source_suffixes, limit=MAX_TEST_SOURCE_FILES):
        if _looks_like_test_file(source):
            continue
        rel = source.relative_to(root_path).as_posix()
        candidates = []
        for test, test_content in tests_with_text:
            if _test_match_reasons(root_path, source, test, test_content):
                candidates.append(test.relative_to(root_path).as_posix())
        if candidates:
            mapping[rel] = sorted(set(candidates))
    return mapping


def related_tests(root: str | Path, file: str) -> list[str]:
    root_path = Path(root).resolve()
    return test_map(root_path).get(_project_relative_path(root_path, file), [])


def explain_related_tests(root: str | Path, file: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    rel = _project_relative_path(root_path, file)
    source = root_path / rel
    tests = related_tests(root_path, rel)
    explanations = [
        {
            "test": test,
            "reasons": _test_match_reasons(root_path, source, root_path / test),
        }
        for test in tests
    ]
    return {"root": str(root_path), "file": rel, "tests": explanations, "count": len(explanations)}


def run_related_tests(root: str | Path, file: str) -> dict[str, Any]:
    tests = related_tests(root, file)
    if not tests:
        return {"ok": False, "error": "No related tests found", "tests": []}
    root_path = Path(root).resolve()
    command_template = _related_test_command_template(root_path, tests)
    cmd = shlex.split(command_template) if command_template else ["pytest", *tests]
    result = _run_command_args(root, cmd, timeout=120)
    return {
        "command": shlex.join(cmd),
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "tests": tests,
    }


def suggest_tests(root: str | Path, changed_files: list[str] | None = None) -> list[str]:
    root_path = Path(root).resolve()
    if not changed_files:
        diff_files = _run_git(root_path, ["diff", "--name-only", "HEAD"]).splitlines()
        changed_files = diff_files
    suggestions = []
    for file in changed_files:
        p = Path(file)
        candidates = [
            root_path / "tests" / f"test_{p.name}",
            root_path / "tests" / p.with_name(f"test_{p.name}"),
        ]
        suggestions.extend(str(c.relative_to(root_path)) for c in candidates if c.exists())
    if not suggestions and (root_path / "pyproject.toml").exists():
        suggestions.append("pytest -q")
    return sorted(set(suggestions))


def save_patch(store: WorkbenchStore, root: str | Path, name: str = "") -> dict[str, Any]:
    diff = _run_git(root, ["diff"])
    patch_dir = store.root / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_name = f"{_slug(name or 'patch')}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.patch"
    patch_path = patch_dir / patch_name
    patch_path.write_text(diff, encoding="utf-8")
    return store.append(
        "patches",
        {
            "name": name or patch_name,
            "path": str(patch_path),
            "bytes": len(diff.encode()),
            "root": str(Path(root).resolve()),
        },
    )


def patch_show(store: WorkbenchStore, patch_id: str) -> dict[str, Any] | None:
    return next((item for item in store.read("patches", []) if item.get("id") == patch_id), None)


def patch_preview(store: WorkbenchStore, patch_id: str, max_chars: int = 12000) -> dict[str, Any]:
    patch = patch_show(store, patch_id)
    if not patch:
        return {"ok": False, "error": f"Patch not found: {patch_id}"}
    path = Path(patch.get("path", ""))
    if not path.exists():
        return {"ok": False, "error": f"Patch file missing: {path}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "ok": True,
        "patch": patch,
        "diff": text[:max_chars],
        "truncated": len(text) > max_chars,
        "stats": _patch_stats(text),
    }


def patch_explain(store: WorkbenchStore, patch_id: str) -> dict[str, Any]:
    preview = patch_preview(store, patch_id)
    if not preview.get("ok"):
        return preview
    stats = preview["stats"]
    summary = [
        f"Patch `{patch_id}` changes {stats['files']} file(s).",
        f"Adds {stats['added']} line(s) and removes {stats['removed']} line(s).",
    ]
    if stats["files_changed"]:
        summary.append("Files: " + ", ".join(stats["files_changed"][:12]))
    return {**preview, "summary": " ".join(summary)}


def apply_saved_patch(store: WorkbenchStore, patch_id: str, reverse: bool = False) -> dict[str, Any]:
    patch = patch_show(store, patch_id)
    if not patch:
        return {"ok": False, "error": f"Patch not found: {patch_id}"}
    path = Path(patch.get("path", ""))
    if not path.exists():
        return {"ok": False, "error": f"Patch file missing: {path}"}
    root = patch.get("root") or "."
    args = ["apply"]
    if reverse:
        args.append("-R")
    check = _run_git_result(root, [*args, "--check", str(path)])
    if check.returncode != 0:
        return {"ok": False, "error": check.stderr or check.stdout, "checked": True}
    applied = _run_git_result(root, [*args, str(path)])
    return {
        "ok": applied.returncode == 0,
        "stdout": applied.stdout,
        "stderr": applied.stderr,
        "patch": patch,
        "reverse": reverse,
    }


def workspace_status(store: WorkbenchStore, root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    git_status = _run_git(root_path, ["status", "--short"])
    pending_plans = [
        item for item in store.read("plans", []) if item.get("status") in {"draft", "pending", "failed"}
    ]
    patches = store.read("patches", [])
    sessions = checkpoint_sessions(store)
    failed_commands = [
        item for item in command_history(store, root_path) if item.get("ok") is False
    ][:10]
    indexes = [
        item for item in store.read("code_indexes", []) if item.get("root") == str(root_path)
    ]
    code_index = indexes[-1] if indexes else None
    return {
        "ok": True,
        "root": str(root_path),
        "git_status": git_status.splitlines(),
        "pending_plans": len(pending_plans),
        "patches": len(patches),
        "checkpoint_sessions": len(sessions),
        "failed_commands": failed_commands,
        "code_index": {
            "present": bool(code_index),
            "updated_at": code_index.get("updated_at", "") if code_index else "",
            "files": len(code_index.get("files", [])) if code_index else 0,
            "symbols": len(code_index.get("symbols", [])) if code_index else 0,
        },
    }


def workspace_clean_report(
    store: WorkbenchStore,
    root: str | Path,
    *,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = status or workspace_status(store, root)
    suggestions = []
    if status["git_status"]:
        suggestions.append("Review or commit local git changes.")
    if status["pending_plans"]:
        suggestions.append("Apply, discard, or inspect pending plans.")
    if status["patches"]:
        suggestions.append("Review saved patches and remove stale ones manually if no longer needed.")
    if not status["code_index"]["present"]:
        suggestions.append("Run `magent code index` to refresh code intelligence.")
    if status["failed_commands"]:
        suggestions.append("Inspect failed command history before release.")
    return {**status, "suggestions": suggestions}


def create_checkpoint(
    username: str,
    root: str | Path,
    path: str | Path,
    operation: str,
    session_id: str = "manual",
) -> dict[str, Any]:
    store = WorkbenchStore(username)
    target = Path(path).expanduser().resolve(strict=False)
    root_path = Path(root).expanduser().resolve(strict=False)
    checkpoint_dir = store.root / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    content_path = ""
    size_bytes = 0
    digest = ""
    if existed and target.is_file():
        data = target.read_bytes()
        size_bytes = len(data)
        digest = hashlib.sha256(data).hexdigest()
        content_name = f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}_{target.name}.bak"
        backup_path = checkpoint_dir / content_name
        backup_path.write_bytes(data)
        content_path = str(backup_path)
    item = store.append(
        "checkpoints",
        {
            "operation": operation,
            "session_id": session_id,
            "root": str(root_path),
            "path": str(target),
            "existed": existed,
            "content_path": content_path,
            "size_bytes": size_bytes,
            "sha256": digest,
            "status": "available",
        },
    )
    return item


def list_checkpoints(store: WorkbenchStore, limit: int = 20) -> list[dict[str, Any]]:
    items = store.read("checkpoints", [])
    return list(reversed(items))[:limit]


def show_checkpoint(store: WorkbenchStore, checkpoint_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in store.read("checkpoints", []) if item.get("id") == checkpoint_id),
        None,
    )


def restore_checkpoint(store: WorkbenchStore, checkpoint_id: str) -> dict[str, Any]:
    item = show_checkpoint(store, checkpoint_id)
    if not item:
        return {"ok": False, "error": f"Checkpoint not found: {checkpoint_id}"}
    target = Path(item.get("path", "")).expanduser().resolve(strict=False)
    if item.get("existed"):
        backup = Path(item.get("content_path", ""))
        if not backup.exists():
            return {"ok": False, "error": f"Checkpoint content missing: {backup}"}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(backup.read_bytes())
    else:
        if target.exists():
            if target.is_dir():
                return {"ok": False, "error": "Refusing to remove directory created after checkpoint"}
            target.unlink()
    store.update_item("checkpoints", checkpoint_id, status="restored", restored_at=now_iso())
    return {"ok": True, "checkpoint": checkpoint_id, "path": str(target)}


def checkpoint_diff(store: WorkbenchStore, checkpoint_id: str) -> dict[str, Any]:
    item = show_checkpoint(store, checkpoint_id)
    if not item:
        return {"ok": False, "error": f"Checkpoint not found: {checkpoint_id}"}
    target = Path(item.get("path", "")).expanduser().resolve(strict=False)
    before = []
    after = []
    if item.get("existed") and item.get("content_path"):
        before = Path(item["content_path"]).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines(keepends=True)
    if target.exists() and target.is_file():
        after = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"{target} (checkpoint)",
            tofile=str(target),
        )
    )
    return {"ok": True, "checkpoint": checkpoint_id, "path": str(target), "diff": diff}


def restore_latest_checkpoint(store: WorkbenchStore) -> dict[str, Any]:
    items = list_checkpoints(store, limit=1)
    if not items:
        return {"ok": False, "error": "No checkpoints found"}
    return restore_checkpoint(store, items[0]["id"])


def checkpoint_sessions(store: WorkbenchStore) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in store.read("checkpoints", []):
        session_id = item.get("session_id") or "manual"
        entry = grouped.setdefault(
            session_id,
            {
                "session_id": session_id,
                "count": 0,
                "paths": set(),
                "first_at": item.get("created_at"),
                "last_at": item.get("created_at"),
            },
        )
        entry["count"] += 1
        entry["paths"].add(item.get("path", ""))
        entry["last_at"] = item.get("created_at") or entry["last_at"]
    result = []
    for entry in grouped.values():
        entry["paths"] = sorted(p for p in entry["paths"] if p)
        result.append(entry)
    return sorted(result, key=lambda item: item.get("last_at") or "", reverse=True)


def checkpoint_session_diff(store: WorkbenchStore, session_id: str) -> dict[str, Any]:
    diffs = []
    for item in store.read("checkpoints", []):
        if (item.get("session_id") or "manual") != session_id:
            continue
        diff = checkpoint_diff(store, item["id"])
        if diff.get("ok") and diff.get("diff"):
            diffs.append(diff)
    return {
        "ok": True,
        "session_id": session_id,
        "diff": "\n".join(item["diff"] for item in diffs),
        "count": len(diffs),
    }


def checkpoint_session_restore(store: WorkbenchStore, session_id: str) -> dict[str, Any]:
    items = [
        item
        for item in reversed(store.read("checkpoints", []))
        if (item.get("session_id") or "manual") == session_id
    ]
    results = [restore_checkpoint(store, item["id"]) for item in items]
    return {"ok": all(item.get("ok") for item in results), "session_id": session_id, "results": results}


def record_command_result(
    store: WorkbenchStore,
    root: str | Path,
    command: str,
    ok: bool,
    source: str = "manual",
) -> dict[str, Any]:
    return store.append(
        "command_history",
        {
            "root": str(Path(root).resolve()),
            "command": command,
            "ok": ok,
            "source": source,
        },
    )


def command_history(store: WorkbenchStore, root: str | Path | None = None) -> list[dict[str, Any]]:
    items = store.read("command_history", [])
    if root:
        root_str = str(Path(root).resolve())
        items = [item for item in items if item.get("root") == root_str]
    return list(reversed(items))


def promote_command(store: WorkbenchStore, root: str | Path, command: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    profiles = store.read("projects", [])
    profile = next((item for item in profiles if item.get("root") == str(root_path)), None)
    if not profile:
        profile = save_project_profile(store, root_path)
        profiles = store.read("projects", [])
    commands = list(profile.get("commands", []))
    if command not in commands:
        commands.append(command)
    for item in profiles:
        if item.get("root") == str(root_path):
            item["commands"] = commands
            item["updated_at"] = now_iso()
    store.write("projects", profiles)
    return {"ok": True, "root": str(root_path), "command": command, "commands": commands}


def env_doctor(root: str | Path) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    checks = []
    for exe in ("git", "python", "node", "npm", "cargo", "go", "docker", "gh"):
        checks.append({"check": exe, "ok": shutil.which(exe) is not None, "detail": shutil.which(exe) or ""})
    for env_file in (".env", ".env.local"):
        path = root_path / env_file
        checks.append({"check": env_file, "ok": path.exists(), "detail": str(path)})
    return checks


def ci_triage(
    root: str | Path,
    logs: bool = False,
    repair_plan: bool = False,
    store: WorkbenchStore | None = None,
    save: bool = False,
) -> dict[str, Any]:
    gh = shutil.which("gh")
    if not gh:
        return {"ok": False, "error": "GitHub CLI not found"}
    result = subprocess.run(
        [
            gh,
            "run",
            "list",
            "--limit",
            "5",
            "--json",
            "databaseId,status,conclusion,displayTitle,headBranch,event,createdAt,url",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    data: dict[str, Any] = {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}
    try:
        runs = json.loads(result.stdout) if result.stdout else []
    except json.JSONDecodeError:
        runs = []
    data["runs"] = runs
    failed = next((run for run in runs if run.get("conclusion") == "failure"), None)
    if (logs or repair_plan) and failed:
        view = subprocess.run(
            [gh, "run", "view", str(failed["databaseId"]), "--log-failed"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        data["failed_run"] = failed
        data["failed_log"] = (view.stdout or view.stderr)[-12000:]
        data["repair_hints"] = _ci_repair_hints(data["failed_log"])
    if repair_plan:
        data["repair_plan"] = ci_repair_plan(root, data)
        if save and store is not None:
            data["saved_plan"] = store.append(
                "plans",
                {
                    "goal": data["repair_plan"]["goal"],
                    "root": str(Path(root).resolve()),
                    "project": Path(root).resolve().name,
                    "status": "pending",
                    "mode": "ci-repair",
                    "steps": data["repair_plan"]["steps"],
                    "checks": [data["repair_plan"].get("reproduce", "")],
                    "ci": data.get("failed_run"),
                    "repair_hints": data["repair_plan"].get("hints", []),
                },
            )
    return data


def ci_repair_plan(root: str | Path, triage: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = project_profile(root)
    failed_log = (triage or {}).get("failed_log", "")
    hints = _ci_repair_hints(failed_log)
    commands = profile.get("commands") or infer_project_commands(Path(root).resolve())
    reproduce = _guess_reproduction_command(failed_log, commands)
    return {
        "goal": "Repair latest failing CI run",
        "root": str(Path(root).resolve()),
        "failed_run": (triage or {}).get("failed_run"),
        "reproduce": reproduce,
        "steps": [
            "Inspect the failed CI log and identify the first failing command.",
            f"Run `{reproduce}` locally." if reproduce else "Run the closest local test/lint command.",
            "Patch the smallest code path that explains the failure.",
            "Rerun the failing command and then the broader project checks.",
            "Review the diff before committing.",
        ],
        "hints": hints,
    }


def project_diagnostics(root: str | Path, store: WorkbenchStore | None = None) -> list[dict[str, Any]]:
    from magent.lsp import lsp_diagnostics

    root_path = Path(root).resolve()
    checks: list[tuple[str, list[str], bool]] = []
    if (root_path / "pyproject.toml").exists() and shutil.which("ruff"):
        checks.append(("ruff", ["ruff", "check", "."], True))
    if (root_path / "pyproject.toml").exists() and shutil.which("pytest"):
        checks.append(("pytest", ["pytest", "-q"], True))
    if (root_path / "package.json").exists() and shutil.which("npm"):
        checks.append(("npm test", ["npm", "test"], True))
    if (root_path / "tsconfig.json").exists() and shutil.which("npx"):
        checks.append(("tsc", ["npx", "tsc", "--noEmit"], True))
    if (root_path / "Cargo.toml").exists() and shutil.which("cargo"):
        checks.append(("cargo check", ["cargo", "check"], True))
    results = [
        {
            "name": name,
            "ok": result.returncode == 0,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
        for name, cmd, _ in checks
        for result in [_run_command_args(root_path, cmd, timeout=90)]
    ]
    if store is not None:
        for item in results:
            record_command_result(store, root_path, item["name"], item["ok"], source="diagnostics")
    lsp_result = lsp_diagnostics(root_path)
    results.append(
        {
            "name": "lsp diagnostics",
            "ok": lsp_result.get("ok", False),
            "stdout": "",
            "stderr": "\n".join(item.get("message", "") for item in lsp_result.get("diagnostics", [])[:10]),
            "diagnostics": lsp_result.get("diagnostics", []),
        }
    )
    return results


def release_check(store: WorkbenchStore | None = None, root: str | Path = ".") -> dict[str, Any]:
    from magent.hooks import run_hooks

    root_path = Path(root).resolve()
    checks: list[dict[str, Any]] = []
    commands = [
        ("tests", ["python", "-m", "pytest", "-q"]),
        ("lint", ["python", "-m", "ruff", "check", "src", "tests"]),
        ("docs", ["magent", "docs", "doctor"]),
    ]
    for name, cmd in commands:
        result = _run_command_args(root_path, cmd, timeout=180)
        item = {
            "name": name,
            "command": shlex.join(cmd),
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-3000:],
            "stderr": result.stderr[-3000:],
        }
        checks.append(item)
        if store is not None:
            record_command_result(store, root_path, item["command"], item["ok"], source="release-check")
    result = {"ok": all(item["ok"] for item in checks), "root": str(root_path), "checks": checks}
    result["hooks"] = run_hooks(root_path, "release_check", result)
    return result


def release_notes(root: str | Path = ".", since: str = "HEAD~5") -> dict[str, Any]:
    root_path = Path(root).resolve()
    log = _run_git(root_path, ["log", "--oneline", f"{since}..HEAD"])
    if not log.strip():
        log = _run_git(root_path, ["log", "--oneline", "-5"])
    commits = [line.strip() for line in log.splitlines() if line.strip()]
    notes = ["# Release Notes", "", "## Changes", ""]
    notes.extend(f"- {commit}" for commit in commits)
    notes.extend(["", "## Verification", "", "- Run `magent release check`."])
    return {"ok": True, "root": str(root_path), "since": since, "commits": commits, "markdown": "\n".join(notes)}


def docs_brief(root: str | Path) -> str:
    profile = project_profile(root)
    return "\n".join(
        [
            f"# {profile['name']} Brief",
            "",
            "## Detected Project Files",
            *[f"- `{file}`" for file in profile["detected_files"]],
            "",
            "## Common Commands",
            *[f"- `{cmd}`" for cmd in profile["commands"]],
        ]
    )


def inspect_data(path: str) -> dict[str, Any]:
    p = Path(path).expanduser().resolve(strict=False)
    if p.suffix.lower() == ".csv":
        with p.open(newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return {"kind": "csv", "columns": reader.fieldnames or [], "rows": len(rows), "sample": rows[:5]}
    if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        conn = sqlite3.connect(str(p))
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        finally:
            conn.close()
        return {"kind": "sqlite", "tables": [row[0] for row in tables]}
    return {"kind": "file", "size_bytes": p.stat().st_size if p.exists() else 0}


def ingest_notes(store: WorkbenchStore, text: str) -> dict[str, Any]:
    tasks = []
    decisions = []
    for line in text.splitlines():
        stripped = line.strip("-* \t")
        if re.search(r"\b(todo|task|follow up|follow-up)\b", stripped, re.IGNORECASE):
            tasks.append(task_add(store, stripped))
        if re.search(r"\b(decision|decided|we will)\b", stripped, re.IGNORECASE):
            decisions.append(store.append("decisions", {"text": stripped}))
    note = store.append("notes", {"text": text, "tasks_created": len(tasks), "decisions": len(decisions)})
    return {"note": note, "tasks": tasks, "decisions": decisions}


def session_timeline(session_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    files = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    if session_id:
        files = [f for f in files if f.stem.startswith(session_id) or session_id in f.name]
    if not files:
        return []
    events = []
    for line in files[0].read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def usage_stats() -> dict[str, Any]:
    sessions = 0
    events = 0
    approx_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cached_tokens = 0
    cache_write_tokens = 0
    cache_miss_tokens = 0
    cost_usd = 0.0
    pruned_results = 0
    pruned_tokens_saved = 0
    tools = Counter()
    for path in LOGS_DIR.glob("*.jsonl"):
        sessions += 1
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events += 1
            approx_tokens += estimate_tokens(json.dumps(event))
            if event.get("event") == "tool_call":
                tools[event.get("tool", "?")] += 1
            if event.get("event") == "token_usage":
                prompt_tokens += int(event.get("prompt_tokens") or 0)
                completion_tokens += int(event.get("completion_tokens") or 0)
                total_tokens += int(event.get("total_tokens") or 0)
                cached_tokens += int(event.get("cached_tokens") or 0)
                cache_write_tokens += int(event.get("cache_write_tokens") or 0)
                cache_miss_tokens += int(event.get("cache_miss_tokens") or 0)
                cost_usd += float(event.get("cost_usd") or 0.0)
            if event.get("event") == "context_pruned":
                pruned_results += int(event.get("pruned") or 0)
                pruned_tokens_saved += int(event.get("approx_tokens_saved") or 0)
    return {
        "sessions": sessions,
        "events": events,
        "approx_tokens_logged": approx_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "cost_usd": round(cost_usd, 6),
        "pruned_results": pruned_results,
        "pruned_tokens_saved": pruned_tokens_saved,
        "top_tools": tools.most_common(10),
    }


def export_dashboard(store: WorkbenchStore, out: str | Path) -> Path:
    out_path = Path(out).expanduser().resolve(strict=False)
    stats = usage_stats()
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>MagAgent Dashboard</title>
<style>body{{font-family:sans-serif;max-width:960px;margin:40px auto;line-height:1.5}}</style></head>
<body>
<h1>MagAgent Dashboard</h1>
<h2>Tasks</h2><pre>{json.dumps(store.read("tasks", []), indent=2)}</pre>
<h2>Plans</h2><pre>{json.dumps(store.read("plans", []), indent=2)}</pre>
<h2>Patches</h2><pre>{json.dumps(store.read("patches", []), indent=2)}</pre>
<h2>Artifacts</h2><pre>{json.dumps(store.read("artifacts", []), indent=2)}</pre>
<h2>Usage</h2><pre>{json.dumps(stats, indent=2)}</pre>
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def serve_dashboard(store: WorkbenchStore, port: int = 7820, open_browser: bool = False) -> dict[str, Any]:
    path = export_dashboard(store, store.root / "dashboard.html")
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, directory=str(path.parent), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/{path.name}"
    if open_browser:
        webbrowser.open(url)
    return {"ok": True, "url": url, "path": str(path)}


def policy_profiles() -> dict[str, dict[str, Any]]:
    return {
        "solo": {"permission_mode": "balanced", "memory": "write", "network": "confirm"},
        "work": {"permission_mode": "balanced", "memory": "review", "network": "confirm"},
        "prod": {"permission_mode": "paranoid", "memory": "review", "network": "block-by-default"},
        "paranoid": {"permission_mode": "paranoid", "memory": "manual", "network": "confirm"},
    }


def _run_git(root: str | Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout
    except Exception:
        return ""


def _run_git_result(root: str | Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_command(root: str | Path, command: str, timeout: int = 60) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(root),
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "command": command,
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def _run_command_args(root: str | Path, cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout)


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _project_relative_path(root: Path, file: str | Path) -> str:
    path = Path(file).expanduser()
    if path.is_absolute():
        try:
            return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _looks_like_test_file(path: Path) -> bool:
    name = path.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or name.endswith("_test.go")
        or name.endswith("_test.rs")
        or "tests" in path.parts
    )


def _test_matches_source(root: Path, source: Path, test: Path) -> bool:
    return bool(_test_match_reasons(root, source, test))


def _test_match_reasons(root: Path, source: Path, test: Path, test_content: str | None = None) -> list[str]:
    source_stem = source.stem
    source_parent = source.parent.name
    test_name = test.name
    test_text = test.as_posix()
    reasons = []
    if source_stem in test.stem or source_stem in test_name:
        reasons.append("test filename contains source stem")
    if source_parent and source_parent in test_text:
        reasons.append("test path contains source package/directory")
    try:
        rel_no_suffix = source.relative_to(root).with_suffix("").as_posix()
        import_name = rel_no_suffix.replace("/", ".")
        content = test_content if test_content is not None else _read_text_safe(test)
        if import_name in content or source_stem in content:
            reasons.append("test imports or references source symbol")
    except Exception:
        pass
    return sorted(set(reasons))


def _related_test_command_template(root: Path, tests: list[str]) -> str:
    commands = load_project_config(root).get("commands", {})
    if isinstance(commands, dict):
        for key in ("test_related", "test"):
            value = commands.get(key)
            if isinstance(value, str) and "{tests}" in value:
                joined = " ".join(shlex.quote(test) for test in tests)
                return value.replace("{tests}", joined)
    suffixes = {Path(test).suffix for test in tests}
    if suffixes & {".js", ".ts"}:
        return "npm test -- " + " ".join(shlex.quote(test) for test in tests)
    if suffixes == {".go"}:
        return "go test ./..."
    if suffixes == {".rs"}:
        return "cargo test"
    return ""


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _package_json_commands(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ["npm test", "npm run build"]
    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    commands = []
    root = path.parent
    runner = "npm run"
    test_runner = "npm test"
    if (root / "pnpm-lock.yaml").exists():
        runner = "pnpm"
        test_runner = "pnpm test"
    elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        runner = "bun run"
        test_runner = "bun test"
    for name in ("test", "lint", "typecheck", "build"):
        if name in scripts:
            commands.append(test_runner if name == "test" else f"{runner} {name}")
    return commands or [test_runner, f"{runner} build"]


def _makefile_commands(path: Path) -> list[str]:
    if not path.exists():
        return []
    targets = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+):(?:\s|$)", line)
        if match and match.group(1) in {"test", "lint", "check", "build"}:
            targets.append(f"make {match.group(1)}")
    return targets


def _justfile_commands(path: Path) -> list[str]:
    if not path.exists():
        return []
    commands = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:\s.*)?:$", line)
        if match and match.group(1) in {"test", "lint", "check", "build"}:
            commands.append(f"just {match.group(1)}")
    return commands


def _review_category(message: str) -> str:
    text = message.lower()
    if "secret" in text or "credential" in text or "injection" in text:
        return "security"
    if "test" in text:
        return "tests"
    if "todo" in text:
        return "maintenance"
    if "debug" in text:
        return "debugging"
    return "correctness"


def _file_risk(file: str) -> str:
    lower = file.lower()
    if any(part in lower for part in ("migration", "schema", "auth", "security", ".env")):
        return "high"
    if any(lower.endswith(suffix) for suffix in (".toml", ".yaml", ".yml", ".json", ".lock")):
        return "medium"
    return "normal"


def _patch_stats(diff: str) -> dict[str, Any]:
    files = []
    added = 0
    removed = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.append(line.removeprefix("+++ b/"))
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {
        "files": len(set(files)),
        "files_changed": sorted(set(files)),
        "added": added,
        "removed": removed,
    }


def _guess_reproduction_command(log: str, commands: list[str]) -> str:
    lower = log.lower()
    for command in commands:
        head = command.split()[0] if command.split() else command
        if command.lower() in lower or head.lower() in lower:
            return command
    for needle, fallback in [
        ("pytest", "pytest -q"),
        ("ruff", "ruff check ."),
        ("npm", "npm test"),
        ("cargo", "cargo test"),
        ("go test", "go test ./..."),
    ]:
        if needle in lower:
            return fallback
    return commands[0] if commands else ""


def _ci_repair_hints(log: str) -> list[str]:
    hints = []
    if "ModuleNotFoundError" in log or "ImportError" in log:
        hints.append("Dependency/import failure: inspect pyproject/package lockfiles and import paths.")
    if "AssertionError" in log or "FAILED" in log:
        hints.append("Test failure: reproduce the failed test locally before editing.")
    if "ruff" in log.lower() or "lint" in log.lower():
        hints.append("Lint failure: run the linter locally and apply the focused fix.")
    if "mypy" in log.lower() or "type" in log.lower():
        hints.append("Type-check failure: inspect the reported symbol and narrow the type contract.")
    return hints or ["Inspect failed_log, reproduce locally, patch, then rerun the failed command."]


def _ignored(path: Path) -> bool:
    return ignored_path(path)


def _iter_project_files(root: Path, *, suffixes: set[str], limit: int):
    yield from iter_project_files(root, suffixes=suffixes, limit=limit)


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def memory_pending_summary(username: str, include_diff: bool = False) -> dict[str, Any]:
    memory_dir = user_memory_dir(username)
    changed = _run_git(memory_dir, ["status", "--short"]) if memory_dir.exists() else ""
    result = {"memory_dir": str(memory_dir), "changed": changed.splitlines()}
    if include_diff and memory_dir.exists():
        result["diff"] = _run_git(memory_dir, ["diff"])
    return result


def memory_approve(username: str, message: str = "Approve MagAgent memory updates") -> dict[str, Any]:
    memory_dir = user_memory_dir(username)
    if not (memory_dir / ".git").exists():
        return {"ok": False, "error": "Memory directory is not a git repository"}
    subprocess.run(["git", "add", "."], cwd=str(memory_dir), capture_output=True, text=True, timeout=30)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(memory_dir),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}
