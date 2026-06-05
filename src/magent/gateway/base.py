"""Gateway base classes — platform-agnostic messaging primitives."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine


@dataclass
class IncomingMessage:
    """A message received from any gateway platform."""
    platform: str           # "slack" | "discord" | "telegram"
    message_id: str         # Platform-native message ID
    user_id: str            # Platform user ID (for allowlist check)
    username: str           # Human-readable name
    channel_id: str         # Channel / chat ID
    text: str               # Raw message text
    is_dm: bool = False     # Direct message (vs. channel/group)
    reply_to: str | None = None  # Thread/reply context
    raw: dict = field(default_factory=dict)  # Raw platform payload


@dataclass
class OutgoingMessage:
    """A response to send back to a platform."""
    platform: str
    channel_id: str
    text: str
    reply_to: str | None = None   # Thread/message to reply to
    is_code: bool = False          # Wrap in code block
    edit_message_id: str | None = None  # Edit an existing message


# Callback type: (IncomingMessage) → runs agent, returns response text
MessageHandler = Callable[[IncomingMessage], Coroutine[Any, Any, str]]


class GatewayAdapter(ABC):
    """Abstract base class for all platform adapters."""

    def __init__(self, config: dict[str, Any], handler: MessageHandler):
        self.config = config
        self.handler = handler
        self._running = False

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Connect to platform and start listening for messages."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect and clean up."""
        ...

    @abstractmethod
    async def post_message(self, msg: OutgoingMessage) -> str | None:
        """Send a message. Returns the message ID if available."""
        ...

    @abstractmethod
    async def update_message(self, channel_id: str, message_id: str, new_text: str) -> None:
        """Edit an existing message (for progress updates)."""
        ...

    @abstractmethod
    async def send_typing(self, channel_id: str) -> None:
        """Send a typing/processing indicator."""
        ...

    async def ack_and_respond(self, msg: IncomingMessage) -> None:
        """
        Standard response flow:
        1. Send "⏳ Working..." immediately
        2. Run agent (may take 30-60s)
        3. Edit/follow-up with result
        """
        # Step 1: Immediate acknowledgement
        ack_id = await self.post_message(OutgoingMessage(
            platform=self.platform_name,
            channel_id=msg.channel_id,
            text="⏳ Working on it...",
            reply_to=msg.message_id,
        ))
        await self.send_typing(msg.channel_id)

        # Step 2: Run agent
        try:
            result = await asyncio.wait_for(
                self.handler(msg),
                timeout=self.config.get("max_task_duration_seconds", 300),
            )
        except asyncio.TimeoutError:
            result = "⚠️ Task timed out. Try breaking it into smaller steps."
        except Exception as e:
            result = f"❌ Error: {e}"

        # Step 3: Update or follow-up
        if ack_id:
            await self.update_message(msg.channel_id, ack_id, f"✅ {result}")
        else:
            await self.post_message(OutgoingMessage(
                platform=self.platform_name,
                channel_id=msg.channel_id,
                text=result,
                reply_to=msg.message_id,
            ))
