"""Stable machine-readable lifecycle events for Agentic Graph execution."""

from __future__ import annotations

import uuid
from typing import Any

from magent.agraph.record import now_iso

GRAPH_EVENT_SCHEMA_VERSION = "magent.graph-event.v1"
GRAPH_STATUS_SCHEMA_VERSION = "magent.graph-status.v1"


def graph_event(
    event_type: str,
    *,
    run_id: str,
    graph_id: str,
    graph_digest: str,
    state: str,
    task_id: str = "",
    node_task_id: str = "",
    node_id: str = "",
    scope_path: str = "",
    title: str = "",
    profile: str = "",
    tool: str = "",
    dependencies: list[str] | None = None,
    attempt: int = 0,
    summary: str = "",
    error_code: str = "",
    error: str = "",
    files_changed: list[str] | None = None,
    usage: dict[str, Any] | None = None,
    blocked_by: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build one additive, versioned JSONL event with stable field names."""
    event = {
        "schema_version": GRAPH_EVENT_SCHEMA_VERSION,
        "event_id": f"gevt_{uuid.uuid4().hex[:16]}",
        "type": event_type,
        "timestamp": now_iso(),
        "run_id": run_id,
        "graph_id": graph_id,
        "graph_digest": graph_digest,
        "task_id": task_id,
        "node_task_id": node_task_id,
        "node_id": node_id,
        "scope_path": scope_path,
        "title": title,
        "profile": profile,
        "tool": tool,
        "dependencies": dependencies or [],
        "state": state,
        "attempt": attempt,
        "summary": summary,
        "error_code": error_code,
        "error": error,
        "files_changed": files_changed or [],
        "usage": usage or {},
        "blocked_by": blocked_by or [],
    }
    return {key: value for key, value in event.items() if value not in ("", [], {}, 0)}
