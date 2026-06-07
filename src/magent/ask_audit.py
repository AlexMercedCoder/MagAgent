"""Lightweight checks for non-interactive ``magent ask`` runs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

FILE_PATTERN = re.compile(
    r"(?<![\w./-])([A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|jsx|html|css|md|toml|json|yaml|yml|txt|sh|rs|go|java|c|cpp|h|hpp|sql))(?![\w/-])"
)


def requested_files(task: str) -> list[str]:
    """Return file-like paths mentioned in a user task, preserving order."""
    seen: set[str] = set()
    files: list[str] = []
    for match in FILE_PATTERN.finditer(task):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            files.append(name)
    return files


def audit_one_shot_task(task: str, cwd: str | Path, scratchpad: dict[str, Any]) -> dict[str, Any]:
    """Summarize obvious completion signals after a one-shot agent run."""
    root = Path(cwd).resolve()
    expected = requested_files(task)
    touched = [str(path) for path in scratchpad.get("files_touched", [])]
    touched_names = {Path(path).name for path in touched}
    existing = [name for name in expected if (root / name).exists()]
    missing = [name for name in expected if name not in touched_names and name not in existing]
    permission_failures = list(scratchpad.get("permission_failures", []))
    ok = not missing and not permission_failures
    return {
        "ok": ok,
        "requested_files": expected,
        "files_touched": touched,
        "existing_requested_files": existing,
        "missing_requested_files": missing,
        "permission_failures": permission_failures,
    }


def render_audit_note(audit: dict[str, Any]) -> str:
    """Render a concise user-facing note for audit warnings."""
    notes: list[str] = []
    missing = audit.get("missing_requested_files") or []
    failures = audit.get("permission_failures") or []
    if missing:
        notes.append("missing requested files: " + ", ".join(missing))
    if failures:
        notes.append("permission required: " + "; ".join(failures))
    return "\n\nTask audit: " + " | ".join(notes) if notes else ""
