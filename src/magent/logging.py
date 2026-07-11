"""JSONL session logger for MagAgent."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
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
            "ts": datetime.now(UTC).isoformat(),
            "session": self.session_id,
            "user": self.username,
            "event": event_type,
            **data,
        }
        self._f.write(json.dumps(record, default=str) + "\n")
        self._f.flush()

    def log_session_start(self, provider: str, model: str, cwd: str) -> None:
        self._write(
            "session_start",
            {
                "provider": provider,
                "model": model,
                "cwd": cwd,
            },
        )

    def log_user_turn(self, turn_number: int, message: str) -> None:
        self._write(
            "user_turn",
            {
                "turn": turn_number,
                "message": message[:500],  # cap log size
            },
        )

    def log_assistant_turn(self, turn_number: int, response: str, tool_calls: int = 0) -> None:
        self._write(
            "assistant_turn",
            {
                "turn": turn_number,
                "response_length": len(response),
                "tool_calls": tool_calls,
                "preview": response[:200],
            },
        )

    def log_tool_call(self, tool_name: str, args: dict, result_ok: bool, tier: int) -> None:
        activity = {}
        raw_activity = args.get("activity") if isinstance(args, dict) else None
        if isinstance(raw_activity, dict):
            activity = {k: str(v)[:180] for k, v in raw_activity.items() if v is not None}
        self._write(
            "tool_call",
            {
                "tool": tool_name,
                "args": {k: str(v)[:100] for k, v in args.items()},
                "activity": activity,
                "ok": result_ok,
                "tier": tier,
            },
        )

    def log_timing(
        self,
        name: str,
        duration_ms: float,
        *,
        turn: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._write(
            "timing",
            {
                "name": name,
                "duration_ms": round(duration_ms, 2),
                "turn": turn,
                "metadata": metadata or {},
            },
        )

    def log_memory_write(self, nodes_written: int, project_slug: str | None) -> None:
        self._write(
            "memory_write",
            {
                "nodes": nodes_written,
                "project": project_slug,
            },
        )

    def log_token_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
        cached_tokens: int = 0,
        cache_hit_tokens: int = 0,
        cache_miss_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_source: str = "",
        cost_usd: float | None = None,
        estimated: bool = False,
    ) -> None:
        self._write(
            "token_usage",
            {
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens
                if total_tokens is not None
                else prompt_tokens + completion_tokens,
                "cached_tokens": cached_tokens,
                "cache_hit_tokens": cache_hit_tokens,
                "cache_miss_tokens": cache_miss_tokens,
                "cache_write_tokens": cache_write_tokens,
                "cache_source": cache_source,
                "cost_usd": cost_usd,
                "estimated": estimated,
            },
        )

    def log_context_pruned(self, reason: str, pruned: int, approx_tokens_saved: int = 0) -> None:
        self._write(
            "context_pruned",
            {
                "reason": reason,
                "pruned": pruned,
                "approx_tokens_saved": approx_tokens_saved,
            },
        )

    def log_session_end(self, total_turns: int) -> None:
        self._write("session_end", {"total_turns": total_turns})
        self._f.close()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._f.close()

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
        results.append(
            {
                "file": f.name,
                "session": first.get("session", f.stem),
                "user": first.get("user", "?"),
                "started": first.get("ts", "?"),
                "ended": last.get("ts", "?") if last.get("event") == "session_end" else "active",
                "events": len(lines),
                "bytes": f.stat().st_size,
            }
        )
    return results
