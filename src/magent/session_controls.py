"""Interactive session controls and diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from magent.config import LOGS_DIR


def last_user_message(conversation: list[dict[str, str]]) -> str:
    """Return the most recent user message from a session conversation."""
    for item in reversed(conversation):
        if item.get("role") == "user":
            return str(item.get("content") or "")
    return ""


def pop_last_turn(conversation: list[dict[str, str]]) -> dict[str, str]:
    """Remove the latest assistant response and user prompt from conversation history."""
    removed: dict[str, str] = {"user": "", "assistant": ""}
    while conversation:
        item = conversation.pop()
        role = item.get("role")
        if role == "assistant" and not removed["assistant"]:
            removed["assistant"] = str(item.get("content") or "")
            continue
        if role == "user":
            removed["user"] = str(item.get("content") or "")
            break
    return removed


def session_usage(log_path: str | Path) -> dict[str, Any]:
    """Aggregate token, cost, timing, and tool-count data from a session log."""
    path = Path(log_path)
    usage = {
        "ok": path.exists(),
        "path": str(path),
        "turns": 0,
        "tool_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "cost_usd": 0.0,
        "slowest": [],
    }
    if not path.exists():
        return usage
    timings: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("event")
        if kind == "assistant_turn":
            usage["turns"] += 1
            usage["tool_calls"] += int(event.get("tool_calls") or 0)
        elif kind == "token_usage":
            usage["prompt_tokens"] += int(event.get("prompt_tokens") or 0)
            usage["completion_tokens"] += int(event.get("completion_tokens") or 0)
            usage["total_tokens"] += int(event.get("total_tokens") or 0)
            usage["cached_tokens"] += int(event.get("cached_tokens") or 0)
            if event.get("cost_usd") is not None:
                usage["cost_usd"] += float(event.get("cost_usd") or 0)
        elif kind == "timing":
            timings.append(
                {
                    "name": event.get("name", ""),
                    "duration_ms": float(event.get("duration_ms") or 0),
                    "turn": event.get("turn"),
                    "metadata": event.get("metadata") or {},
                }
            )
    timings.sort(key=lambda item: item["duration_ms"], reverse=True)
    usage["slowest"] = timings[:8]
    return usage


def recent_insights(limit: int = 5) -> dict[str, Any]:
    """Summarize recent session logs for diagnostics."""
    logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if LOGS_DIR.exists() else []
    sessions = [session_usage(path) for path in logs[:limit]]
    totals = {
        "sessions": len(sessions),
        "turns": sum(int(item.get("turns") or 0) for item in sessions),
        "tool_calls": sum(int(item.get("tool_calls") or 0) for item in sessions),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in sessions),
        "cached_tokens": sum(int(item.get("cached_tokens") or 0) for item in sessions),
        "cost_usd": round(sum(float(item.get("cost_usd") or 0) for item in sessions), 6),
    }
    return {"ok": True, "totals": totals, "sessions": sessions}
