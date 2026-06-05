"""Telegram gateway adapter.

Setup: see docs/gateway/setup-telegram.md
Requires: python-telegram-bot>=21.0
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from rich.console import Console

from magent.gateway.base import GatewayAdapter, IncomingMessage, MessageHandler, OutgoingMessage

console = Console()
log = logging.getLogger("magent.gateway.telegram")

TELEGRAM_MAX_LEN = 4000


class TelegramAdapter(GatewayAdapter):
    """
    Telegram adapter using python-telegram-bot (polling mode — no webhook needed).

    Required config keys:
      bot_token   str   Telegram bot token from @BotFather

    Optional config keys:
      respond_to_groups   bool  Respond in group chats (default True)
      respond_to_dms      bool  Respond in private chats (default True)
      command_prefix      str   Prefix for group trigger, e.g. "/agent" (default: @mention)
    """

    def __init__(self, config: dict[str, Any], handler: MessageHandler):
        super().__init__(config, handler)
        self._app = None
        self._bot = None

    @property
    def platform_name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        try:
            from telegram import Bot, Update
            from telegram.ext import (
                Application,
                filters,
            )
            from telegram.ext import (
                MessageHandler as TGHandler,
            )
        except ImportError:
            raise RuntimeError(
                "python-telegram-bot is not installed. Run: pip install 'python-telegram-bot>=21.0'"
            )

        bot_token = self.config.get("bot_token", "")
        if not bot_token:
            raise ValueError(
                "Telegram gateway requires 'bot_token' in [gateway.telegram] of config.toml"
            )

        respond_to_groups = self.config.get("respond_to_groups", True)
        respond_to_dms = self.config.get("respond_to_dms", True)
        command_prefix = self.config.get("command_prefix", "")

        app = Application.builder().token(bot_token).build()
        self._app = app
        self._bot = app.bot
        self._running = True

        # Get bot's own username (for @mention detection in groups)
        bot_info = await app.bot.get_me()
        bot_username = bot_info.username
        console.print(f"[bold green]✓ Telegram gateway connected as @{bot_username}[/bold green]")

        async def handle_message(update: Update, context) -> None:
            if not update.message or not update.message.text:
                return

            msg_obj = update.message
            chat = msg_obj.chat
            is_dm = chat.type == "private"
            is_group = chat.type in ("group", "supergroup")

            if is_dm and not respond_to_dms:
                return
            if is_group and not respond_to_groups:
                return

            text = msg_obj.text.strip()

            # In groups: only respond if @mentioned or command prefix
            if is_group:
                mentioned = f"@{bot_username}" in text
                has_prefix = command_prefix and text.startswith(command_prefix)
                if not mentioned and not has_prefix:
                    return
                if mentioned:
                    text = text.replace(f"@{bot_username}", "").strip()
                elif has_prefix:
                    text = text[len(command_prefix) :].strip()

            if not text:
                return

            user = msg_obj.from_user
            msg = IncomingMessage(
                platform="telegram",
                message_id=str(msg_obj.message_id),
                user_id=str(user.id),
                username=user.full_name or user.username or str(user.id),
                channel_id=str(chat.id),
                text=text,
                is_dm=is_dm,
                raw={"chat_type": chat.type},
            )

            await self.ack_and_respond(msg)

        # Register handler for all text messages
        app.add_handler(TGHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Also handle /ask command explicitly (optional convenience)
        from telegram.ext import CommandHandler

        async def cmd_ask(update: Update, context) -> None:
            text = " ".join(context.args)
            if not text:
                await update.message.reply_text("Usage: /ask <your question>")
                return
            user = update.message.from_user
            msg = IncomingMessage(
                platform="telegram",
                message_id=str(update.message.message_id),
                user_id=str(user.id),
                username=user.full_name or str(user.id),
                channel_id=str(update.message.chat.id),
                text=text,
                is_dm=update.message.chat.type == "private",
            )
            await self.ack_and_respond(msg)

        app.add_handler(CommandHandler("ask", cmd_ask))
        app.add_handler(CommandHandler("agent", cmd_ask))  # alias

        # Start polling (drops pending updates from before startup)
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                log.debug(f"Telegram shutdown: {e}")
        console.print("[dim]Telegram gateway stopped.[/dim]")

    async def post_message(self, msg: OutgoingMessage) -> str | None:
        """Send a Telegram message. Returns message ID string."""
        if not self._bot:
            return None
        try:
            chunks = _chunk_telegram(msg.text)
            sent = None
            for i, chunk in enumerate(chunks):
                reply_id = int(msg.reply_to) if (msg.reply_to and i == 0) else None
                kwargs: dict[str, Any] = {
                    "chat_id": int(msg.channel_id),
                    "text": chunk,
                    "parse_mode": "Markdown",
                }
                if reply_id:
                    kwargs["reply_to_message_id"] = reply_id
                sent = await self._bot.send_message(**kwargs)
            return str(sent.message_id) if sent else None
        except Exception:
            # Retry without Markdown if parse error
            try:
                sent = await self._bot.send_message(
                    chat_id=int(msg.channel_id),
                    text=_chunk_telegram(msg.text)[0],
                )
                return str(sent.message_id)
            except Exception as e2:
                log.error(f"Telegram post_message error: {e2}")
                return None

    async def update_message(self, channel_id: str, message_id: str, new_text: str) -> None:
        """Edit an existing Telegram message."""
        if not self._bot:
            return
        try:
            chunks = _chunk_telegram(new_text)
            await self._bot.edit_message_text(
                chat_id=int(channel_id),
                message_id=int(message_id),
                text=chunks[0],
                parse_mode="Markdown",
            )
            # Post additional chunks as follow-up messages
            for extra in chunks[1:]:
                await self._bot.send_message(
                    chat_id=int(channel_id),
                    text=extra,
                )
        except Exception:
            # Edit may fail if content unchanged or too old — post as new message
            try:
                await self._bot.send_message(
                    chat_id=int(channel_id),
                    text=_chunk_telegram(new_text)[0],
                )
            except Exception as e:
                log.error(f"Telegram update_message error: {e}")

    async def send_typing(self, channel_id: str) -> None:
        """Send Telegram 'typing...' action."""
        if not self._bot:
            return
        with contextlib.suppress(Exception):
            await self._bot.send_chat_action(
                chat_id=int(channel_id),
                action="typing",
            )


def _chunk_telegram(text: str, max_len: int = TELEGRAM_MAX_LEN) -> list[str]:
    """Split long text into Telegram-safe chunks."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
