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
    workspace_clean_report,
    workspace_status,
)


def cockpit_state(
    store: Any,
    project: str | Path = ".",
    *,
    workspace: dict[str, Any] | None = None,
    clean_report: dict[str, Any] | None = None,
    project_doctor_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an action-oriented project cockpit summary."""
    root = Path(project).resolve()
    plans = list_plans(store)
    commands = command_history(store, root)
    failed_commands = [item for item in commands if item.get("ok") is False]
    workspace = workspace or workspace_status(store, root)
    clean_report = clean_report or workspace_clean_report(store, root, status=workspace)
    project_doctor_result = project_doctor_result or project_doctor(root, store)
    return {
        "ok": True,
        "project": str(root),
        "workspace": workspace,
        "clean_report": clean_report,
        "project_doctor": project_doctor_result,
        "plans": plans[:20],
        "pending_plans": [item for item in plans if item.get("status") in {"draft", "pending", "failed"}][:10],
        "memory_inbox": memory_inbox(store, root, limit=10).get("candidates", []),
        "recipes": list_recipes(store, root)[:10],
        "sandbox_runs": list_sandbox_runs(store, limit=10),
        "failed_commands": failed_commands[:10],
        "release_check": _latest_release_check(commands),
    }


def _latest_release_check(commands: list[dict[str, Any]]) -> dict[str, Any]:
    for item in commands:
        if item.get("source") == "release-check":
            return {
                "ok": item.get("ok"),
                "last_run": item.get("created_at", ""),
                "command": item.get("command", ""),
                "status": "cached",
            }
    return {
        "ok": None,
        "status": "not_run",
        "command": "magent release check",
        "detail": "Run release checks explicitly; cockpit refresh does not execute tests.",
    }
