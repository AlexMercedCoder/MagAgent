"""Project playbook loading and command-routine helpers."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PLAYBOOK_PATH = Path(".magent") / "playbook.toml"


def playbook_path(root: str | Path = ".") -> Path:
    """Return the canonical playbook path for a project root."""
    return Path(root).resolve() / PLAYBOOK_PATH


def load_playbook(root: str | Path = ".") -> dict[str, Any]:
    """Load ``.magent/playbook.toml`` if present."""
    path = playbook_path(root)
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def playbook_summary(root: str | Path = ".") -> dict[str, Any]:
    """Summarize commands and routines exposed by the project playbook."""
    path = playbook_path(root)
    data = load_playbook(root)
    commands = _command_map(data)
    release = _string_list(data.get("release", {}).get("checklist") if isinstance(data.get("release"), dict) else [])
    review = data.get("review", {}) if isinstance(data.get("review"), dict) else {}
    context = data.get("context", {}) if isinstance(data.get("context"), dict) else {}
    return {
        "ok": bool(data) and "_error" not in data,
        "exists": path.exists(),
        "path": str(path),
        "error": data.get("_error", ""),
        "commands": commands,
        "release_checklist": release,
        "review_rules": _string_list(review.get("rules", [])),
        "context_defaults": context,
    }


def playbook_commands(root: str | Path = ".") -> list[str]:
    """Return executable command strings configured by the playbook."""
    summary = playbook_summary(root)
    commands = []
    for value in summary.get("commands", {}).values():
        if isinstance(value, str):
            commands.append(value)
        elif isinstance(value, list):
            commands.extend(str(item) for item in value if str(item).strip())
    return sorted(dict.fromkeys(commands))


def playbook_template() -> str:
    """Return a starter project playbook."""
    return """# MagAgent project playbook

[commands]
test = ["pytest -q"]
lint = "ruff check src tests"
build = "python -m build"

[release]
checklist = [
  "Run test and lint commands",
  "Update docs and changelog",
  "Build and check distribution artifacts",
]

[review]
rules = [
  "Source changes should include focused tests",
  "User-facing behavior changes should update docs",
]

[context]
briefing_topics = ["architecture", "testing", "commands"]
"""


def _command_map(data: dict[str, Any]) -> dict[str, str | list[str]]:
    commands = data.get("commands", {})
    if not isinstance(commands, dict):
        return {}
    mapped: dict[str, str | list[str]] = {}
    for key, value in commands.items():
        if isinstance(value, str) and value.strip():
            mapped[str(key)] = value.strip()
        elif isinstance(value, list):
            mapped[str(key)] = [str(item).strip() for item in value if str(item).strip()]
    return mapped


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []
