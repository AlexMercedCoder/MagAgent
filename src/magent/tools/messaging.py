"""Agent-facing local session messaging tools."""

from __future__ import annotations

import asyncio

from magent.session_messaging import list_sessions, send_session_message
from magent.tools.types import ToolResult


class MessagingToolsMixin:
    username: str
    session_id: str

    async def list_sessions(self) -> ToolResult:
        peers = await asyncio.to_thread(list_sessions, self.username)
        peers = [peer for peer in peers if peer.get("session_id") != self.session_id]
        return {"ok": True, "sessions": peers, "count": len(peers)}

    async def send_session_message(
        self, target: str, message: str, task_id: str = ""
    ) -> ToolResult:
        return await asyncio.to_thread(
            send_session_message,
            self.username,
            self.session_id,
            target,
            message,
            task_id=task_id,
        )
