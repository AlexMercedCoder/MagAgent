"""Stable user-facing agent activity event helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

AgentEventType = Literal[
    "model_round_started",
    "model_round_finished",
    "tool_started",
    "tool_finished",
    "permission_requested",
    "artifact_audit",
    "assistant_message",
]


class AgentActivityEvent(TypedDict, total=False):
    type: AgentEventType
    ts: str
    turn: int
    tool: str
    round: int
    ok: bool
    duration_ms: float
    activity: dict[str, str]
    detail: dict[str, Any]


def activity_event(
    event_type: AgentEventType,
    *,
    turn: int = 0,
    tool: str = "",
    round_number: int = 0,
    ok: bool | None = None,
    duration_ms: float | None = None,
    activity: dict[str, str] | None = None,
    detail: dict[str, Any] | None = None,
) -> AgentActivityEvent:
    """Build a stable activity event for logs, CLIs, and desktop clients."""
    event: AgentActivityEvent = {
        "type": event_type,
        "ts": datetime.now(UTC).isoformat(),
    }
    if turn:
        event["turn"] = turn
    if tool:
        event["tool"] = tool
    if round_number:
        event["round"] = round_number
    if ok is not None:
        event["ok"] = ok
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 2)
    if activity:
        event["activity"] = activity
    if detail:
        event["detail"] = detail
    return event
