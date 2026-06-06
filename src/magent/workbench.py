"""Durable local workbench primitives for coding and productivity workflows."""

from __future__ import annotations

import csv
import difflib
import hashlib
import json
import re
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

from magent.config import LOGS_DIR, USERS_DIR, user_memory_dir
from magent.tokens import estimate_tokens

WORKBENCH_DIRNAME = "workbench"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class WorkbenchStore:
    """Simple JSON-backed store scoped to one MagAgent user."""

    def __init__(self, username: str):
        self.username = username
        self.root = USERS_DIR / username / WORKBENCH_DIRNAME
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, default: Any) -> Any:
        path = self.root / f"{name}.json"
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def write(self, name: str, data: Any) -> None:
        path = self.root / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def append(self, name: str, item: dict[str, Any]) -> dict[str, Any]:
        data = self.read(name, [])
        next_id = _next_id(data, name.rstrip("s"))
        item = {"id": next_id, "created_at": now_iso(), **item}
        data.append(item)
        self.write(name, data)
        return item

    def update_item(self, name: str, item_id: str, **updates: Any) -> dict[str, Any] | None:
        data = self.read(name, [])
        for item in data:
            if item.get("id") == item_id:
                item.update(updates)
                item["updated_at"] = now_iso()
                self.write(name, data)
                return item
        return None


def _next_id(items: list[dict[str, Any]], prefix: str) -> str:
    existing = [
        int(str(item.get("id", "")).rsplit("_", 1)[-1])
        for item in items
        if str(item.get("id", "")).rsplit("_", 1)[-1].isdigit()
    ]
    return f"{prefix}_{(max(existing) if existing else 0) + 1:04d}"


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
        },
    )


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
    if (root / "package.json").exists():
        commands.extend(_package_json_commands(root / "package.json"))
    if (root / "Cargo.toml").exists():
        commands.extend(["cargo test", "cargo clippy"])
    if (root / "go.mod").exists():
        commands.extend(["go test ./..."])
    commands.extend(_makefile_commands(root / "Makefile"))
    commands.extend(_justfile_commands(root / "justfile"))
    commands.extend(_justfile_commands(root / "Justfile"))
    return sorted(dict.fromkeys(command for command in commands if command.strip()))


def load_project_config(root: str | Path) -> dict[str, Any]:
    path = Path(root).resolve() / ".magent" / "config.toml"
    return _read_toml(path)


def build_plan(root: str | Path, goal: str) -> str:
    profile = project_profile(root)
    lines = [
        f"# Plan: {goal}",
        "",
        f"Project: `{profile['name']}`",
        f"Root: `{profile['root']}`",
        "",
        "## Suggested Steps",
        "1. Inspect relevant files with `outline_file` and targeted range reads.",
        "2. Make small patch-oriented edits.",
        "3. Run the narrowest relevant checks.",
        "4. Review the diff and update docs/tests if behavior changed.",
        "5. Record decisions/tasks/artifacts in the workbench.",
        "",
        "## Likely Checks",
    ]
    commands = profile.get("commands") or ["git diff --stat"]
    lines.extend(f"- `{command}`" for command in commands)
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


def list_plans(store: WorkbenchStore, status: str | None = None) -> list[dict[str, Any]]:
    plans = store.read("plans", [])
    if status:
        plans = [plan for plan in plans if plan.get("status") == status]
    return plans


def apply_plan(store: WorkbenchStore, plan_id: str, run_checks: bool = False) -> dict[str, Any]:
    plans = store.read("plans", [])
    plan = next((item for item in plans if item.get("id") == plan_id), None)
    if not plan:
        return {"ok": False, "error": f"Plan not found: {plan_id}"}
    check_results = []
    if run_checks:
        for command in plan.get("checks", []):
            check_results.append(_run_command(plan.get("root", "."), command, timeout=120))
    updated = store.update_item(
        "plans",
        plan_id,
        status="applied",
        applied_at=now_iso(),
        check_results=check_results,
    )
    return {"ok": True, "plan": updated, "checks": check_results}


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
    findings = review_diff(root, base)
    categories = Counter(item.get("category", "general") for item in findings)
    return {
        "ok": not any(item.get("priority") in {"P0", "P1"} for item in findings),
        "base": base,
        "findings": findings,
        "categories": dict(categories),
        "changed_files": _run_git(root, ["diff", "--name-only", base, "--"]).splitlines(),
    }


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


def apply_saved_patch(store: WorkbenchStore, patch_id: str, reverse: bool = False) -> dict[str, Any]:
    patch = next((item for item in store.read("patches", []) if item.get("id") == patch_id), None)
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


def create_checkpoint(
    username: str,
    root: str | Path,
    path: str | Path,
    operation: str,
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


def env_doctor(root: str | Path) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    checks = []
    for exe in ("git", "python", "node", "npm", "cargo", "go", "docker", "gh"):
        checks.append({"check": exe, "ok": shutil.which(exe) is not None, "detail": shutil.which(exe) or ""})
    for env_file in (".env", ".env.local"):
        path = root_path / env_file
        checks.append({"check": env_file, "ok": path.exists(), "detail": str(path)})
    return checks


def ci_triage(root: str | Path, logs: bool = False, repair_plan: bool = False) -> dict[str, Any]:
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


def project_diagnostics(root: str | Path) -> list[dict[str, Any]]:
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
    return [
        {
            "name": name,
            "ok": result.returncode == 0,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
        for name, cmd, _ in checks
        for result in [_run_command_args(root_path, cmd, timeout=90)]
    ]


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
    for name in ("test", "lint", "typecheck", "build"):
        if name in scripts:
            commands.append("npm test" if name == "test" else f"npm run {name}")
    return commands or ["npm test", "npm run build"]


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
    parts = set(path.parts)
    return bool(parts & {".git", ".venv", "__pycache__", "node_modules", "target"})


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
