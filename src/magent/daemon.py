"""Durable local background queue and worker helpers."""

from __future__ import annotations

import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

QUEUE_STORE = "daemon_queue"


def enqueue_task(
    store: Any,
    kind: str,
    payload: dict[str, Any],
    *,
    project: str | Path = ".",
    run_at: str = "",
) -> dict[str, Any]:
    return store.append(
        QUEUE_STORE,
        {
            "kind": kind,
            "payload": payload,
            "project": str(Path(project).resolve()),
            "run_at": run_at,
            "status": "pending",
            "attempts": 0,
        },
    )


def list_queue(store: Any, status: str = "") -> dict[str, Any]:
    items = list(reversed(store.read(QUEUE_STORE, [])))
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"ok": True, "tasks": items}


def run_once(store: Any, *, limit: int = 1) -> dict[str, Any]:
    items = store.read(QUEUE_STORE, [])
    now = datetime.now(UTC)
    results = []
    for item in items:
        if len(results) >= limit:
            break
        if item.get("status") != "pending" or not _due(item, now):
            continue
        item["status"] = "running"
        item["attempts"] = int(item.get("attempts") or 0) + 1
        result = _execute_item(item)
        item["status"] = "done" if result.get("ok") else "failed"
        item["result"] = result
        item["updated_at"] = datetime.now(UTC).isoformat()
        results.append({"task": item, "result": result})
    store.write(QUEUE_STORE, items)
    return {"ok": all(item["result"].get("ok") for item in results), "ran": len(results), "results": results}


def enqueue_due_followups(store: Any) -> dict[str, Any]:
    followups = store.read("followups", [])
    created = []
    now = datetime.now(UTC)
    for item in followups:
        if item.get("status") == "queued":
            continue
        run_at = item.get("when") or item.get("run_at") or ""
        if run_at and not _time_due(run_at, now):
            continue
        task = enqueue_task(
            store,
            "ask",
            {"task": item.get("text", ""), "source": f"followup/{item.get('id', '')}"},
            run_at=run_at,
        )
        item["status"] = "queued"
        created.append(task)
    store.write("followups", followups)
    return {"ok": True, "queued": created}


def _due(item: dict[str, Any], now: datetime) -> bool:
    run_at = item.get("run_at") or ""
    return not run_at or _time_due(run_at, now)


def _time_due(raw: str, now: datetime) -> bool:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= now


def _execute_item(item: dict[str, Any]) -> dict[str, Any]:
    kind = item.get("kind")
    payload = item.get("payload", {})
    project = item.get("project") or "."
    if kind == "recipe":
        command = ["magent", "recipe", "run", payload.get("name", ""), "--project", project]
    elif kind == "orchestrated_goal":
        command = ["magent", "goal-run", payload.get("id", ""), "--project", project, "--json"]
    elif kind == "plan":
        command = ["magent", "plan-apply", payload.get("id", ""), "--yes"]
    elif kind == "shell":
        return _run_shell(payload.get("command", ""), project)
    else:
        command = ["magent", "ask", payload.get("task", ""), "--project", project]
    return _run_command(command, project)


def _run_shell(command: str, project: str | Path) -> dict[str, Any]:
    if not command:
        return {"ok": False, "error": "Empty shell task"}
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return {"ok": False, "command": command, "error": str(e)}
    return _run_command(argv, project)


def _run_command(command: list[str], project: str | Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return {
            "ok": result.returncode == 0,
            "command": " ".join(command),
            "returncode": result.returncode,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-4000:],
        }
    except Exception as e:
        return {"ok": False, "command": " ".join(command), "error": str(e)}
