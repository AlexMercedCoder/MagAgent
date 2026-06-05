"""Message router: authentication, rate-limiting, and AgentSession dispatch."""

from __future__ import annotations

import contextlib
import time
from collections import defaultdict
from typing import Any

from rich.console import Console

from magent.config import get_current_user
from magent.gateway.base import IncomingMessage

console = Console()


class RateLimiter:
    """Token-bucket rate limiter per user."""

    def __init__(self, max_per_minute: int = 10):
        self.max_per_minute = max_per_minute
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        window = now - 60.0
        bucket = self._buckets[user_id]
        # Remove timestamps older than 1 minute
        self._buckets[user_id] = [t for t in bucket if t > window]
        if len(self._buckets[user_id]) >= self.max_per_minute:
            return False
        self._buckets[user_id].append(now)
        return True

    def seconds_until_reset(self, user_id: str) -> float:
        if not self._buckets[user_id]:
            return 0.0
        oldest = min(self._buckets[user_id])
        return max(0.0, 60.0 - (time.time() - oldest))


class MessageRouter:
    """
    Handles authentication, rate-limiting, and routing messages to AgentSession.

    Config keys (from [gateway] in config.toml):
      allowed_user_ids      list[str]   Platform user IDs allowed to interact
      allowed_channel_ids   list[str]   Optional: restrict to specific channels
      require_mention       bool        Only respond when bot is @mentioned (default False for DMs)
      rate_limit_per_minute int         Max requests per user per minute (default 10)
      max_task_duration_seconds int     Agent timeout (default 300)
      username              str         MagAgent user profile to use (default: current user)
    """

    def __init__(self, gateway_config: dict[str, Any]):
        self.config = gateway_config
        self.allowed_user_ids: set[str] = set(gateway_config.get("allowed_user_ids", []))
        self.allowed_channel_ids: set[str] = set(gateway_config.get("allowed_channel_ids", []))
        self.rate_limiter = RateLimiter(
            max_per_minute=gateway_config.get("rate_limit_per_minute", 10)
        )
        self._username = gateway_config.get("username") or get_current_user() or "default"
        self._session_cache: dict[str, Any] = {}  # channel_id → AgentSession

    def is_authorized(self, msg: IncomingMessage) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        if self.allowed_user_ids and msg.user_id not in self.allowed_user_ids:
            return False, f"User {msg.user_id} not in allowlist"

        if self.allowed_channel_ids and msg.channel_id not in self.allowed_channel_ids:
            return False, f"Channel {msg.channel_id} not in allowlist"

        if not self.rate_limiter.is_allowed(msg.user_id):
            wait = self.rate_limiter.seconds_until_reset(msg.user_id)
            return False, f"Rate limit exceeded. Try again in {wait:.0f}s"

        return True, ""

    def _get_session(self, channel_id: str) -> Any:
        """Get or create an AgentSession for a channel (persistent per channel)."""
        if channel_id not in self._session_cache:
            from magent.config import load_config
            from magent.providers import build_provider

            config = load_config(self._username)
            p_cfg = config.provider_config(config.default_provider)
            api_key = config.resolve_api_key(config.default_provider) or p_cfg.get("api_key")

            provider = build_provider(config.default_provider, config.default_model, api_key, p_cfg)
            ext_p_cfg = config.provider_config(config.extraction_provider)
            ext_key = config.resolve_api_key(config.extraction_provider) or ext_p_cfg.get("api_key")
            ext_provider = build_provider(
                config.extraction_provider, config.extraction_model, ext_key, ext_p_cfg
            )

            import os

            from magent.agent import AgentSession

            session = AgentSession(
                username=self._username,
                config=config,
                provider=provider,
                extraction_provider=ext_provider,
                cwd=os.getcwd(),
                project_slug=f"gateway_{channel_id[:12]}",
            )
            self._session_cache[channel_id] = session

        return self._session_cache[channel_id]

    async def handle(self, msg: IncomingMessage) -> str:
        """Auth-check and dispatch a message. Returns response text."""
        allowed, reason = self.is_authorized(msg)
        if not allowed:
            console.print(
                f"[dim red]Gateway blocked [{msg.platform}] {msg.username}: {reason}[/dim red]"
            )
            return f"⛔ {reason}"

        console.print(
            f"[dim cyan]Gateway [{msg.platform}][/dim cyan] "
            f"[bold]{msg.username}[/bold]: {msg.text[:80]}"
        )

        try:
            session = self._get_session(msg.channel_id)
            response = await session.chat(msg.text)
            return response
        except Exception as e:
            console.print(f"[red]Gateway session error: {e}[/red]")
            return f"❌ Agent error: {e}"

    async def close_all_sessions(self) -> None:
        """End all open agent sessions (writes memory, closes logs)."""
        for session in self._session_cache.values():
            with contextlib.suppress(Exception):
                await session.end_session()
        self._session_cache.clear()
