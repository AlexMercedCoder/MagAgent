"""Workbench-backed event log for trust and auditability."""

from __future__ import annotations

from typing import Any

EVENT_STORE = "events"


def record_event(store: Any, kind: str, title: str, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append a structured event to the current user's workbench."""
    return store.append(EVENT_STORE, {"kind": kind, "title": title, "detail": detail or {}})


def list_events(store: Any, limit: int = 50, kind: str = "") -> dict[str, Any]:
    """List recent workbench events."""
    events = list(reversed(store.read(EVENT_STORE, [])))
    if kind:
        events = [event for event in events if event.get("kind") == kind]
    return {"ok": True, "events": events[:limit]}


def show_event(store: Any, event_id: str) -> dict[str, Any]:
    """Show one event by id."""
    event = next((item for item in store.read(EVENT_STORE, []) if item.get("id") == event_id), None)
    if not event:
        return {"ok": False, "error": f"Event not found: {event_id}"}
    return {"ok": True, "event": event}
