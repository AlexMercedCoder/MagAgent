"""Gateway runner — starts one or more platform adapters and manages the event loop."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import Any

from rich.console import Console

from magent.config import CONFIG_DIR
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
        runner = asyncio.gather(
            *(adapter.start() for adapter in self._adapters),
            return_exceptions=True,
        )

        def _shutdown():
            # Cancelling *every* task included this coroutine itself, so the
            # `finally: await self.shutdown()` never ran: adapters kept their
            # connections and the PID file survived. Cancel only the runner.
            console.print("\n[dim]Gateway shutting down...[/dim]")
            runner.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _shutdown)

        try:
            await runner
        except asyncio.CancelledError:
            pass
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError, ValueError):
                    loop.remove_signal_handler(sig)
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
    except (OSError, ValueError):
        GATEWAY_PID_FILE.unlink(missing_ok=True)
        return False, None

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        GATEWAY_PID_FILE.unlink(missing_ok=True)
        return False, None
    except PermissionError:
        # The process exists but belongs to another uid — that is *alive*, not
        # dead. Treating it as dead deleted the PID file of a running gateway.
        return True, pid
    return True, pid


EXAMPLE_GATEWAY_CONFIG = """
# ─────────────────────────────────────────────
# Gateway Configuration
# Add this to your ~/.config/magent/config.toml
# ─────────────────────────────────────────────

[gateway]
# MagAgent user profile to use for gateway sessions
username = "alex"

# Platform user IDs allowed to send instructions. REQUIRED: while this is
# empty the gateway refuses every message, because a gateway session runs
# headless and auto-resolves permission checks.
# Slack: User ID like "U01234ABCDE" (Settings → Profile → ⋮ → Copy member ID)
# Discord: User ID (enable Developer Mode → right-click user → Copy ID)
# Telegram: Numeric user ID (send /start to @userinfobot)
allowed_user_ids = []

# Accept anyone who can reach the bot. Only set this on a private workspace —
# it hands every member a headless agent on this machine.
# allow_anyone = false

# Optional: restrict to specific channel IDs only
# allowed_channel_ids = []

# In group channels, only respond when the bot is @mentioned. DMs always pass.
# require_mention = false

# Allow `/approve always` from chat to write trusted shell patterns into the
# on-disk profile, where they also apply to future local CLI sessions.
# allow_persistent_approvals = false
# admin_user_ids = []

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
