"""Reconstruct a past conversation so a session can be resumed.

Conversations were in-memory only: closing the terminal lost the thread. Turns
are now recorded in full to `<session>.transcript.jsonl` and read back here into
the shape `AgentSession.conversation` expects.

Sessions recorded before transcripts existed still resume, from the event log's
per-turn previews — lossy, and reported as such via `lossy: true`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["list_resumable_sessions", "load_session_transcript", "resolve_session_log"]


def _log_dir() -> Path:
    from magent.config import LOGS_DIR

    return Path(LOGS_DIR)


def _read_events(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # one torn line must not lose the session
        if isinstance(event, dict):
            events.append(event)
    return events


def list_resumable_sessions(limit: int = 20, user: str | None = None) -> list[dict[str, Any]]:
    """Recent sessions that have at least one exchange, newest first."""
    directory = _log_dir()
    if not directory.exists():
        return []

    sessions = []
    for path in sorted(directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
        events = _read_events(path)
        if not events:
            continue

        first = events[0]
        if user and first.get("user") != user:
            continue

        turns = [event for event in events if event.get("event") in {"user_turn", "assistant_turn"}]
        if not turns:
            continue

        opening = next((event for event in events if event.get("event") == "user_turn"), {})
        sessions.append(
            {
                "session": first.get("session", path.stem),
                "file": str(path),
                "user": first.get("user", ""),
                "started": first.get("ts", ""),
                "turns": len([event for event in turns if event.get("event") == "user_turn"]),
                "preview": str(opening.get("message", ""))[:120],
            }
        )
        if len(sessions) >= limit:
            break

    return sessions


def resolve_session_log(session_id: str = "") -> Path | None:
    """The log for `session_id`, or the most recent session when it is empty."""
    directory = _log_dir()
    if not directory.exists():
        return None

    candidates = sorted(directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not session_id:
        return next((path for path in candidates if _read_events(path)), None)

    for path in candidates:
        if path.stem == session_id:
            return path
        events = _read_events(path)
        if events and str(events[0].get("session", "")) == session_id:
            return path
    return None


def load_session_transcript(session_id: str = "", *, max_turns: int = 40) -> dict[str, Any]:
    """Return `{ok, session, conversation}` ready to assign to a session.

    Only the last `max_turns` exchanges are restored: a very long history would
    otherwise blow the context window on the first prompt of the resumed
    session.
    """
    path = resolve_session_log(session_id)
    if path is None:
        return {"ok": False, "error": f"No session log found for {session_id or 'the most recent session'}"}

    # The full transcript is authoritative. The event log only keeps a
    # 500/200-character preview per turn, so it is a lossy last resort for
    # sessions recorded before transcripts existed.
    conversation: list[dict[str, str]] = []
    lossy = False

    transcript = path.with_suffix(".transcript.jsonl")
    for event in _read_events(transcript):
        role = str(event.get("role", ""))
        if role in {"user", "assistant"}:
            conversation.append({"role": role, "content": str(event.get("content", ""))})

    if not conversation:
        lossy = True
        for event in _read_events(path):
            kind = event.get("event")
            if kind == "user_turn":
                conversation.append({"role": "user", "content": str(event.get("message", ""))})
            elif kind == "assistant_turn":
                conversation.append({"role": "assistant", "content": str(event.get("preview", ""))})

    if not conversation:
        return {"ok": False, "error": f"{path.name} contains no conversation turns"}

    trimmed = conversation[-(max_turns * 2) :]
    events = _read_events(path)
    return {
        "ok": True,
        "session": str(events[0].get("session", path.stem)) if events else path.stem,
        "file": str(path),
        "user": str(events[0].get("user", "")) if events else "",
        "conversation": trimmed,
        "turns": sum(1 for item in trimmed if item["role"] == "user"),
        "truncated": len(trimmed) < len(conversation),
        # True when only preview-length text was available.
        "lossy": lossy,
    }
