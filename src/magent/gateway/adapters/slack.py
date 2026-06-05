"""Slack gateway adapter — uses Socket Mode (no public URL required).

Setup: see docs/gateway/setup-slack.md
Requires: slack-bolt>=1.18, slack-sdk>=3.27
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from rich.console import Console

from magent.gateway.base import GatewayAdapter, IncomingMessage, MessageHandler, OutgoingMessage

console = Console()
log = logging.getLogger("magent.gateway.slack")


class SlackAdapter(GatewayAdapter):
    """
    Slack adapter using slack-bolt with Socket Mode.

    Required config keys:
      bot_token   str  xoxb-... (Bot User OAuth Token)
      app_token   str  xapp-... (App-Level Token with connections:write scope)

    Optional config keys:
      strip_mention  bool  Strip leading @BotName from message (default True)
    """

    def __init__(self, config: dict[str, Any], handler: MessageHandler):
        super().__init__(config, handler)
        self._app = None
        self._socket_handler = None
        self._bot_user_id: str | None = None

    @property
    def platform_name(self) -> str:
        return "slack"

    def _make_app(self):
        """Lazily import and initialise slack-bolt App."""
        try:
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
            from slack_bolt.async_app import AsyncApp
        except ImportError as e:
            raise RuntimeError(
                "slack-bolt is not installed. Run: pip install 'slack-bolt>=1.18'"
            ) from e

        bot_token = self.config.get("bot_token", "")
        app_token = self.config.get("app_token", "")
        if not bot_token or not app_token:
            raise ValueError(
                "Slack gateway requires 'bot_token' (xoxb-...) and 'app_token' (xapp-...) "
                "in [gateway.slack] of config.toml"
            )

        app = AsyncApp(token=bot_token)
        self._app = app
        self._socket_handler = AsyncSocketModeHandler(app, app_token)
        return app

    def _strip_mention(self, text: str) -> str:
        """Remove <@UXXXXXX> bot mention from start of message."""
        import re

        return re.sub(r"^<@[A-Z0-9]+>\s*", "", text).strip()

    async def start(self) -> None:
        app = self._make_app()
        self._running = True

        # Fetch bot's own user ID (to detect self-mentions)
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self.config["bot_token"])
            info = await client.auth_test()
            self._bot_user_id = info["user_id"]
        except Exception as e:
            log.warning(f"Could not fetch bot user ID: {e}")

        @app.event("message")
        async def on_message(event, say, client):
            # Ignore bot's own messages
            if event.get("bot_id") or event.get("subtype"):
                return

            text = event.get("text", "").strip()
            if not text:
                return

            # Strip bot mention if present
            if self.config.get("strip_mention", True):
                text = self._strip_mention(text)
            if not text:
                return

            msg = IncomingMessage(
                platform="slack",
                message_id=event.get("ts", ""),
                user_id=event.get("user", ""),
                username=event.get("user", "unknown"),
                channel_id=event.get("channel", ""),
                text=text,
                is_dm=event.get("channel_type") == "im",
                reply_to=event.get("thread_ts") or event.get("ts"),
                raw=event,
            )

            # Try to resolve display name
            try:
                user_info = await client.users_info(user=msg.user_id)
                msg.username = user_info["user"]["real_name"] or msg.user_id
            except Exception:
                pass

            await self.ack_and_respond(msg)

        @app.event("app_mention")
        async def on_mention(event, say):
            """Also handle @mention events (fires in addition to 'message' in channels)."""
            pass  # Handled by on_message above

        console.print("[bold green]✓ Slack gateway starting (Socket Mode)...[/bold green]")
        await self._socket_handler.start_async()

    async def stop(self) -> None:
        self._running = False
        if self._socket_handler:
            with contextlib.suppress(Exception):
                await self._socket_handler.close_async()
        console.print("[dim]Slack gateway stopped.[/dim]")

    async def post_message(self, msg: OutgoingMessage) -> str | None:
        """Post a message to Slack. Returns the message timestamp (ts) as ID."""
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self.config["bot_token"])

            kwargs: dict[str, Any] = {
                "channel": msg.channel_id,
                "text": _truncate_slack(msg.text),
            }
            if msg.reply_to:
                kwargs["thread_ts"] = msg.reply_to

            resp = await client.chat_postMessage(**kwargs)
            return resp["ts"]
        except Exception as e:
            log.error(f"Slack post_message error: {e}")
            return None

    async def update_message(self, channel_id: str, message_id: str, new_text: str) -> None:
        """Edit an existing Slack message."""
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            client = AsyncWebClient(token=self.config["bot_token"])
            await client.chat_update(
                channel=channel_id,
                ts=message_id,
                text=_truncate_slack(new_text),
            )
        except Exception as e:
            log.error(f"Slack update_message error: {e}")

    async def send_typing(self, channel_id: str) -> None:
        """Slack doesn't support typing indicators via API — no-op."""
        pass


def _truncate_slack(text: str, max_len: int = 3900) -> str:
    """Slack messages have a 4000-char limit. Truncate with notice."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n\n_[Response truncated — use `magent` CLI for full output]_"
