"""Gateway runner — starts one or more platform adapters and manages the event loop."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from magent.config import CONFIG_DIR
from magent.gateway.base import IncomingMessage
from magent.gateway.router import MessageRouter

console = Console()

GATEWAY_PID_FILE = CONFIG_DIR / "gateway.pid"
GATEWAY_LOG_FILE = CONFIG_DIR / "logs" / "gateway.log"


class GatewayRunner:
    """
    Manages one or more platform adapters concurrently.

    Usage:
        runner = GatewayRunner(global_config)
        asyncio.run(runner.run(platforms=["slack", "discord", "telegram"]))
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        gateway_cfg = config.get("gateway", {})
        self.router = MessageRouter(gateway_cfg)
        self._adapters: list[Any] = []

    def _make_adapter(self, platform: str) -> Any:
        gateway_cfg = self.config.get("gateway", {})
        platform_cfg = {**gateway_cfg, **gateway_cfg.get(platform, {})}
        handler = self.router.handle

        if platform == "slack":
            from magent.gateway.adapters.slack import SlackAdapter

            return SlackAdapter(platform_cfg, handler)
        elif platform == "discord":
            from magent.gateway.adapters.discord import DiscordAdapter

            return DiscordAdapter(platform_cfg, handler)
        elif platform == "telegram":
            from magent.gateway.adapters.telegram import TelegramAdapter

            return TelegramAdapter(platform_cfg, handler)
        else:
            raise ValueError(
                f"Unknown platform: {platform!r}. Must be slack, discord, or telegram."
            )

    async def run(self, platforms: list[str]) -> None:
        if not platforms:
            raise ValueError("No platforms specified")

        console.print(
            f"[bold magenta]🚀 MagAgent Gateway[/bold magenta] starting on: "
            f"[cyan]{', '.join(platforms)}[/cyan]"
        )

        self._adapters = [self._make_adapter(p) for p in platforms]

        # Write PID file
        GATEWAY_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        GATEWAY_PID_FILE.write_text(str(os.getpid()))

        # Graceful shutdown on SIGINT / SIGTERM
        loop = asyncio.get_running_loop()

        def _shutdown():
            console.print("\n[dim]Gateway shutting down...[/dim]")
            for t in asyncio.all_tasks(loop):
                t.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                pass  # Windows

        try:
            await asyncio.gather(
                *(adapter.start() for adapter in self._adapters),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        for adapter in self._adapters:
            with contextlib.suppress(Exception):
                await adapter.stop()
        await self.router.close_all_sessions()
        if GATEWAY_PID_FILE.exists():
            GATEWAY_PID_FILE.unlink()
        console.print("[dim green]Gateway stopped cleanly.[/dim green]")


def read_gateway_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return the [gateway] section of config, raising if not present."""
    gw = config.get("gateway", {})
    if not gw:
        raise RuntimeError(
            "No [gateway] section found in config.toml. "
            "Run 'magent gateway init' to generate an example config."
        )
    return gw


def is_gateway_running() -> tuple[bool, int | None]:
    """Check if a gateway process is running from its PID file."""
    if not GATEWAY_PID_FILE.exists():
        return False, None
    try:
        pid = int(GATEWAY_PID_FILE.read_text().strip())
        # Check if process exists
        os.kill(pid, 0)
        return True, pid
    except (ProcessLookupError, PermissionError, ValueError):
        GATEWAY_PID_FILE.unlink(missing_ok=True)
        return False, None


EXAMPLE_GATEWAY_CONFIG = """
# ─────────────────────────────────────────────
# Gateway Configuration
# Add this to your ~/.config/magent/config.toml
# ─────────────────────────────────────────────

[gateway]
# MagAgent user profile to use for gateway sessions
username = "alex"

# Platform user IDs allowed to send instructions
# Slack: User ID like "U01234ABCDE" (Settings → Profile → ⋮ → Copy member ID)
# Discord: User ID (enable Developer Mode → right-click user → Copy ID)
# Telegram: Numeric user ID (send /start to @userinfobot)
allowed_user_ids = []

# Optional: restrict to specific channel IDs only
# allowed_channel_ids = []

# Max requests per user per minute (default: 10)
rate_limit_per_minute = 10

# Max seconds to wait for agent to complete a task (default: 300)
max_task_duration_seconds = 300

# ── Slack ──────────────────────────────────────
[gateway.slack]
# Bot User OAuth Token (xoxb-...)
bot_token = ""
# App-Level Token for Socket Mode (xapp-...)
app_token = ""

# ── Discord ────────────────────────────────────
[gateway.discord]
# Discord bot token from discord.com/developers/applications
bot_token = ""
# Optional command prefix in servers (besides @mention)
# command_prefix = "!agent "
respond_to_dms = true
respond_in_guilds = true

# ── Telegram ───────────────────────────────────
[gateway.telegram]
# Bot token from @BotFather
bot_token = ""
respond_to_dms = true
respond_to_groups = true
# command_prefix = "/agent"
"""
