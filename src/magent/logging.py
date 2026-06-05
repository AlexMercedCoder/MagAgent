"""JSONL session logger for MagAgent."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from magent.config import LOGS_DIR


class SessionLogger:
    """Writes structured JSONL event logs for a session."""

    def __init__(self, session_id: str, username: str):
        self.session_id = session_id
        self.username = username
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._path = LOGS_DIR / f"{session_id}.jsonl"
        self._f = self._path.open("a", encoding="utf-8")

    def _write(self, event_type: str, data: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": self.session_id,
            "user": self.username,
            "event": event_type,
            **data,
        }
        self._f.write(json.dumps(record, default=str) + "\n")
        self._f.flush()

    def log_session_start(self, provider: str, model: str, cwd: str) -> None:
        self._write("session_start", {
            "provider": provider,
            "model": model,
            "cwd": cwd,
        })

    def log_user_turn(self, turn_number: int, message: str) -> None:
        self._write("user_turn", {
            "turn": turn_number,
            "message": message[:500],  # cap log size
        })

    def log_assistant_turn(self, turn_number: int, response: str, tool_calls: int = 0) -> None:
        self._write("assistant_turn", {
            "turn": turn_number,
            "response_length": len(response),
            "tool_calls": tool_calls,
            "preview": response[:200],
        })

    def log_tool_call(self, tool_name: str, args: dict, result_ok: bool, tier: int) -> None:
        self._write("tool_call", {
            "tool": tool_name,
            "args": {k: str(v)[:100] for k, v in args.items()},
            "ok": result_ok,
            "tier": tier,
        })

    def log_memory_write(self, nodes_written: int, project_slug: str | None) -> None:
        self._write("memory_write", {
            "nodes": nodes_written,
            "project": project_slug,
        })

    def log_session_end(self, total_turns: int) -> None:
        self._write("session_end", {"total_turns": total_turns})
        self._f.close()

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass

    @property
    def path(self) -> Path:
        return self._path


def list_session_logs(limit: int = 20) -> list[dict[str, Any]]:
    """List recent session log files with basic metadata."""
    if not LOGS_DIR.exists():
        return []
    files = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    results = []
    for f in files[:limit]:
        lines = f.read_text().splitlines()
        first = json.loads(lines[0]) if lines else {}
        last = json.loads(lines[-1]) if lines else {}
        results.append({
            "file": f.name,
            "session": first.get("session", f.stem),
            "user": first.get("user", "?"),
            "started": first.get("ts", "?"),
            "ended": last.get("ts", "?") if last.get("event") == "session_end" else "active",
            "events": len(lines),
            "bytes": f.stat().st_size,
        })
    return results
