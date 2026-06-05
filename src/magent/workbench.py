"""Durable local workbench primitives for coding and productivity workflows."""

from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
import subprocess
from collections import Counter
from datetime import UTC, datetime
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
    commands = infer_project_commands(root_path)
    return {
        "root": str(root_path),
        "name": root_path.name,
        "detected_files": files,
        "commands": commands,
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
    if (root / "pyproject.toml").exists():
        commands.extend(["pytest -q", "ruff check src tests"])
    if (root / "package.json").exists():
        commands.extend(["npm test", "npm run build"])
    if (root / "Cargo.toml").exists():
        commands.extend(["cargo test", "cargo clippy"])
    if (root / "go.mod").exists():
        commands.extend(["go test ./..."])
    return commands


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


def review_diff(root: str | Path, base: str = "HEAD") -> list[dict[str, Any]]:
    diff = _run_git(root, ["diff", base, "--"])
    findings = []
    patterns = [
        ("P1", r"api[_-]?key|secret|password|token\s*=", "Possible secret or credential in diff."),
        ("P2", r"TODO|FIXME", "New TODO/FIXME may need tracking."),
        ("P2", r"except Exception\s*:\s*pass", "Broad silent exception can hide failures."),
        ("P3", r"print\(", "Debug print added; verify it is intentional."),
    ]
    for lineno, line in enumerate(diff.splitlines(), start=1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for priority, pattern, message in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append(
                    {
                        "priority": priority,
                        "line": lineno,
                        "message": message,
                        "evidence": line[:160],
                    }
                )
    return findings


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


def env_doctor(root: str | Path) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    checks = []
    for exe in ("git", "python", "node", "npm", "cargo", "go", "docker", "gh"):
        checks.append({"check": exe, "ok": shutil.which(exe) is not None, "detail": shutil.which(exe) or ""})
    for env_file in (".env", ".env.local"):
        path = root_path / env_file
        checks.append({"check": env_file, "ok": path.exists(), "detail": str(path)})
    return checks


def ci_triage(root: str | Path) -> dict[str, Any]:
    gh = shutil.which("gh")
    if not gh:
        return {"ok": False, "error": "GitHub CLI not found"}
    result = subprocess.run(
        [gh, "run", "list", "--limit", "5"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


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
    return {
        "sessions": sessions,
        "events": events,
        "approx_tokens_logged": approx_tokens,
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
<h2>Artifacts</h2><pre>{json.dumps(store.read("artifacts", []), indent=2)}</pre>
<h2>Usage</h2><pre>{json.dumps(stats, indent=2)}</pre>
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


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


def _ignored(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & {".git", ".venv", "__pycache__", "node_modules", "target"})


def memory_pending_summary(username: str) -> dict[str, Any]:
    memory_dir = user_memory_dir(username)
    changed = _run_git(memory_dir, ["status", "--short"]) if memory_dir.exists() else ""
    return {"memory_dir": str(memory_dir), "changed": changed.splitlines()}
