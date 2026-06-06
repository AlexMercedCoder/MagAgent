"""Aggregated workbench cockpit state for UI and CLI surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magent.memory_inbox import memory_inbox
from magent.recipes import list_recipes
from magent.sandbox import list_sandbox_runs
from magent.workbench import (
    command_history,
    list_plans,
    project_doctor,
    release_check,
    workspace_clean_report,
    workspace_status,
)


def cockpit_state(store: Any, project: str | Path = ".") -> dict[str, Any]:
    """Return an action-oriented project cockpit summary."""
    root = Path(project).resolve()
    plans = list_plans(store)
    commands = command_history(store, root)
    failed_commands = [item for item in commands if item.get("ok") is False]
    return {
        "ok": True,
        "project": str(root),
        "workspace": workspace_status(store, root),
        "clean_report": workspace_clean_report(store, root),
        "project_doctor": project_doctor(root, store),
        "plans": plans[:20],
        "pending_plans": [item for item in plans if item.get("status") in {"draft", "pending", "failed"}][:10],
        "memory_inbox": memory_inbox(store, root, limit=10).get("candidates", []),
        "recipes": list_recipes(store, root)[:10],
        "sandbox_runs": list_sandbox_runs(store, limit=10),
        "failed_commands": failed_commands[:10],
        "release_check": release_check(store, root),
    }
