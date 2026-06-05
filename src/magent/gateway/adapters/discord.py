"""Discord gateway adapter.

Setup: see docs/gateway/setup-discord.md
Requires: discord.py>=2.3
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console

from magent.gateway.base import GatewayAdapter, IncomingMessage, OutgoingMessage, MessageHandler

console = Console()
log = logging.getLogger("magent.gateway.discord")

# Discord message limit
DISCORD_MAX_LEN = 1900


class DiscordAdapter(GatewayAdapter):
    """
    Discord adapter using discord.py.

    Required config keys:
      bot_token   str   Discord bot token from discord.com/developers

    Optional config keys:
      respond_to_dms      bool  Respond to DMs (default True)
      respond_in_guilds   bool  Respond in server channels (default True)
      command_prefix      str   Prefix to trigger bot in channels, e.g. "!" (default: @mention only)
    """

    def __init__(self, config: dict[str, Any], handler: MessageHandler):
        super().__init__(config, handler)
        self._client = None

    @property
    def platform_name(self) -> str:
        return "discord"

    async def start(self) -> None:
        try:
            import discord
        except ImportError:
            raise RuntimeError(
                "discord.py is not installed. Run: pip install 'discord.py>=2.3'"
            )

        bot_token = self.config.get("bot_token", "")
        if not bot_token:
            raise ValueError(
                "Discord gateway requires 'bot_token' in [gateway.discord] of config.toml"
            )

        intents = discord.Intents.default()
        intents.message_content = True   # Required for reading message text
        intents.dm_messages = True

        client = discord.Client(intents=intents)
        self._client = client
        self._running = True

        respond_to_dms = self.config.get("respond_to_dms", True)
        respond_in_guilds = self.config.get("respond_in_guilds", True)
        command_prefix = self.config.get("command_prefix", "")

        @client.event
        async def on_ready():
            console.print(
                f"[bold green]✓ Discord gateway connected as "
                f"[cyan]{client.user}[/cyan] (ID: {client.user.id})[/bold green]"
            )

        @client.event
        async def on_message(message: discord.Message):
            # Ignore own messages
            if message.author == client.user:
                return

            is_dm = isinstance(message.channel, discord.DMChannel)
            is_guild = message.guild is not None

            if is_dm and not respond_to_dms:
                return
            if is_guild and not respond_in_guilds:
                return

            text = message.content.strip()

            # In guild channels: require @mention or command prefix
            if is_guild:
                bot_mentioned = client.user in message.mentions
                has_prefix = command_prefix and text.startswith(command_prefix)
                if not bot_mentioned and not has_prefix:
                    return
                # Strip mention and prefix
                if bot_mentioned:
                    text = text.replace(f"<@{client.user.id}>", "").strip()
                    text = text.replace(f"<@!{client.user.id}>", "").strip()
                elif has_prefix:
                    text = text[len(command_prefix):].strip()

            if not text:
                return

            msg = IncomingMessage(
                platform="discord",
                message_id=str(message.id),
                user_id=str(message.author.id),
                username=message.author.display_name,
                channel_id=str(message.channel.id),
                text=text,
                is_dm=is_dm,
                raw={"guild_id": str(message.guild.id) if message.guild else None},
            )

            await self.ack_and_respond(msg)

        console.print("[bold green]✓ Discord gateway starting...[/bold green]")
        await client.start(bot_token)

    async def stop(self) -> None:
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        console.print("[dim]Discord gateway stopped.[/dim]")

    async def post_message(self, msg: OutgoingMessage) -> str | None:
        """Post a message to Discord. Returns message ID string."""
        if not self._client:
            return None
        try:
            import discord
            channel = self._client.get_channel(int(msg.channel_id))
            if channel is None:
                # Try fetching if not in cache (DM channels)
                channel = await self._client.fetch_channel(int(msg.channel_id))

            chunks = _chunk_discord(msg.text)
            sent = None
            for chunk in chunks:
                sent = await channel.send(chunk)
            return str(sent.id) if sent else None
        except Exception as e:
            log.error(f"Discord post_message error: {e}")
            return None

    async def update_message(self, channel_id: str, message_id: str, new_text: str) -> None:
        """Edit an existing Discord message."""
        if not self._client:
            return
        try:
            import discord
            channel = self._client.get_channel(int(channel_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(channel_id))
            message = await channel.fetch_message(int(message_id))
            chunks = _chunk_discord(new_text)
            await message.edit(content=chunks[0])
            # If response grew beyond one chunk, post the rest as follow-ups
            for extra in chunks[1:]:
                await channel.send(extra)
        except Exception as e:
            log.error(f"Discord update_message error: {e}")

    async def send_typing(self, channel_id: str) -> None:
        """Send typing indicator in a Discord channel."""
        if not self._client:
            return
        try:
            channel = self._client.get_channel(int(channel_id))
            if channel:
                async with channel.typing():
                    await asyncio.sleep(0)
        except Exception:
            pass


def _chunk_discord(text: str, max_len: int = DISCORD_MAX_LEN) -> list[str]:
    """Split long text into Discord-safe chunks."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at a newline
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
