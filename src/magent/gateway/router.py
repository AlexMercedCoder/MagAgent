"""Message router: authentication, rate-limiting, and AgentSession dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

from rich.console import Console

from magent.config import get_current_user
from magent.gateway.base import IncomingMessage
from magent.secret_scrub import correlation_id, safe_error_message, scrub_secrets

console = Console()


class RateLimiter:
    """Token-bucket rate limiter per user.

    Bounded: the bucket map used to grow forever, and merely *reading* a user's
    reset time minted a permanent entry for them, so any stranger sending one
    blocked message left a row behind.
    """

    def __init__(self, max_per_minute: int = 10, max_tracked_users: int = 10_000):
        self.max_per_minute = max_per_minute
        self.max_tracked_users = max_tracked_users
        self._buckets: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        window = now - 60.0
        for user_id in [key for key, stamps in self._buckets.items() if not stamps or max(stamps) <= window]:
            del self._buckets[user_id]
        # Hard ceiling in case a flood outruns natural expiry.
        while len(self._buckets) > self.max_tracked_users:
            oldest = min(self._buckets, key=lambda key: max(self._buckets[key], default=0.0))
            del self._buckets[oldest]

    def is_allowed(self, user_id: str) -> bool:
        now = time.time()
        window = now - 60.0
        self._prune(now)
        recent = [stamp for stamp in self._buckets.get(user_id, []) if stamp > window]
        if len(recent) >= self.max_per_minute:
            self._buckets[user_id] = recent
            return False
        recent.append(now)
        self._buckets[user_id] = recent
        return True

    def seconds_until_reset(self, user_id: str) -> float:
        stamps = self._buckets.get(user_id)  # read-only: never creates an entry
        if not stamps:
            return 0.0
        return max(0.0, 60.0 - (time.time() - min(stamps)))


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
        self.allowed_user_ids: set[str] = {
            str(user_id) for user_id in gateway_config.get("allowed_user_ids", [])
        }
        self.allowed_channel_ids: set[str] = {
            str(channel_id) for channel_id in gateway_config.get("allowed_channel_ids", [])
        }
        self.allow_anyone: bool = bool(gateway_config.get("allow_anyone", False))
        self.require_mention: bool = bool(gateway_config.get("require_mention", False))
        self.allow_persistent_approvals: bool = bool(
            gateway_config.get("allow_persistent_approvals", False)
        )
        self.admin_user_ids: set[str] = {
            str(user_id) for user_id in gateway_config.get("admin_user_ids", [])
        }
        self.rate_limiter = RateLimiter(
            max_per_minute=gateway_config.get("rate_limit_per_minute", 10)
        )
        self._username = gateway_config.get("username") or get_current_user() or "default"
        self._session_cache: dict[str, Any] = {}  # channel_id → AgentSession
        self._channel_locks: dict[str, asyncio.Lock] = {}

    def is_authorized(self, msg: IncomingMessage) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        # Fail closed. An empty allowlist used to admit everyone in the
        # workspace/server to a headless session where permission checks
        # auto-resolve; opening that up is now a deliberate opt-in.
        if not self.allowed_user_ids and not self.allow_anyone:
            return False, (
                "Gateway allowlist is empty. Set gateway.allowed_user_ids, "
                "or gateway.allow_anyone = true to accept everyone."
            )

        if self.allowed_user_ids and msg.user_id not in self.allowed_user_ids:
            return False, f"User {msg.user_id} not in allowlist"

        if self.allowed_channel_ids and msg.channel_id not in self.allowed_channel_ids:
            return False, f"Channel {msg.channel_id} not in allowlist"

        if not self.rate_limiter.is_allowed(msg.user_id):
            wait = self.rate_limiter.seconds_until_reset(msg.user_id)
            return False, f"Rate limit exceeded. Try again in {wait:.0f}s"

        return True, ""

    def should_respond(self, msg: IncomingMessage) -> bool:
        """Honour `require_mention`, which was documented but never implemented.

        Adapters call this before handling; a direct message always counts.
        """
        if not self.require_mention:
            return True
        if msg.is_dm:
            return True
        return bool(getattr(msg, "mentions_bot", False))

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
                interactive_permissions=False,
            )
            self._session_cache[channel_id] = session

        return self._session_cache[channel_id]

    def _handle_approval_command(self, msg: IncomingMessage) -> str | None:
        text = msg.text.strip()
        if not text.startswith("/approve"):
            return None
        parts = text.split(maxsplit=2)
        if len(parts) < 3 or parts[1] not in {"session", "always"}:
            return "Usage: `/approve session <exact command>` or `/approve always <exact command>`"
        scope, command = parts[1], parts[2].strip()
        if not command:
            return "No command provided to approve."
        if scope == "session":
            session = self._get_session(msg.channel_id)
            if command not in session.tools.session_shell_patterns:
                session.tools.session_shell_patterns.append(command)
            return f"Approved for this gateway session: `{command}`"

        # `/approve always` writes into the on-disk user profile, which then
        # applies to future *local* CLI sessions. A chat message should not be
        # able to do that unless the operator has said so.
        if not self.allow_persistent_approvals:
            return (
                "Persistent approvals are disabled for this gateway. "
                "Use `/approve session <command>`, or set "
                "gateway.allow_persistent_approvals = true to allow saving."
            )
        if self.admin_user_ids and msg.user_id not in self.admin_user_ids:
            return "Only gateway admins may save approvals for future sessions."

        from magent.config import load_user_profile, save_user_profile

        profile = load_user_profile(self._username)
        permissions = profile.setdefault("permissions", {})
        patterns = list(permissions.get("trusted_shell_patterns") or [])
        if command not in patterns:
            patterns.append(command)
        permissions["trusted_shell_patterns"] = patterns
        save_user_profile(self._username, profile)
        if msg.channel_id in self._session_cache and command not in self._session_cache[msg.channel_id].tools.trusted_shell_patterns:
            self._session_cache[msg.channel_id].tools.trusted_shell_patterns.append(command)
        return f"Approved for future sessions: `{command}`"

    def _channel_lock(self, channel_id: str) -> asyncio.Lock:
        lock = self._channel_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._channel_locks[channel_id] = lock
        return lock

    async def handle(self, msg: IncomingMessage) -> str:
        """Auth-check and dispatch a message. Returns response text."""
        allowed, reason = self.is_authorized(msg)
        if not allowed:
            console.print(
                f"[dim red]Gateway blocked [{msg.platform}] {msg.username}: {reason}[/dim red]"
            )
            return f"⛔ {reason}"

        # One AgentSession per channel, entered concurrently by overlapping
        # messages, corrupts the shared conversation and scratchpad.
        async with self._channel_lock(msg.channel_id):
            return await self._handle_locked(msg)

    async def _handle_locked(self, msg: IncomingMessage) -> str:
        console.print(
            f"[dim cyan]Gateway [{msg.platform}][/dim cyan] "
            f"[bold]{msg.username}[/bold]: {msg.text[:80]}"
        )

        bridge = None
        try:
            graph_result = self._handle_graph_command(msg)
            if graph_result is not None:
                return graph_result
            approval_result = self._handle_approval_command(msg)
            if approval_result is not None:
                return approval_result
            if self.config.get("background"):
                from magent.daemon import enqueue_task
                from magent.workbench import WorkbenchStore

                task = enqueue_task(
                    WorkbenchStore(self._username),
                    "ask",
                    {"task": msg.text, "source": f"{msg.platform}/{msg.channel_id}"},
                    project=".",
                )
                return (
                    f"Queued background task {task['id']} "
                    f"(execution {task['execution_task_id']})"
                )
            session = self._get_session(msg.channel_id)
            from magent.execution_bridge import SessionTaskBridge
            from magent.workbench_store import WorkbenchStore

            bridge = SessionTaskBridge(
                WorkbenchStore(self._username),
                session,
                kind="gateway_message",
                title=msg.text[:500],
                project=session.cwd,
                permission_policy="headless",
                provider=session.provider,
                metadata={
                    "platform": msg.platform,
                    "channel_id": msg.channel_id,
                    "gateway_user_id": msg.user_id,
                },
            )
            response = await session.chat(msg.text)
            bridge.complete({"ok": True, "response_chars": len(response)})
            return response
        except Exception as e:
            if bridge is not None:
                with contextlib.suppress(Exception):
                    bridge.fail(e)
            # The detail stays local; the chat platform gets a reference, because
            # provider exception strings can carry request URLs, headers and keys.
            reference = correlation_id()
            console.print(f"[red]Gateway session error (ref {reference}): {scrub_secrets(str(e))}[/red]")
            return f"❌ {safe_error_message(e, reference=reference)}"

    def _handle_graph_command(self, msg: IncomingMessage) -> str | None:
        """Validate, plan, or queue AGS graphs from an authorized gateway chat."""
        import json
        import shlex

        if not msg.text.strip().startswith("/graph "):
            return None
        try:
            parts = shlex.split(msg.text.strip())
        except ValueError as exc:
            return f"Invalid graph command: {exc}"
        if len(parts) < 3 or parts[1] not in {"validate", "plan", "run"}:
            return "Usage: /graph validate|plan|run <path> [--yes]"
        action, raw_path = parts[1], parts[2]
        project = Path(str(self.config.get("project") or ".")).resolve()
        path = (project / raw_path).resolve(strict=False)
        if path != project and project not in path.parents:
            return "Graph path must stay inside the configured gateway project."
        if action == "validate":
            from magent.desktop_api import graph_validate

            return json.dumps(graph_validate(str(path)), indent=2, default=str)[:7000]
        if action == "plan":
            from magent.desktop_api import graph_plan

            return json.dumps(graph_plan(str(path)), indent=2, default=str)[:7000]
        from magent.daemon import enqueue_task
        from magent.workbench import WorkbenchStore

        task = enqueue_task(
            WorkbenchStore(self._username),
            "agraph",
            {"path": str(path), "yes": "--yes" in parts, "source": f"{msg.platform}/{msg.channel_id}"},
            project=project,
        )
        return f"Queued Agentic Graph {task['id']} (execution {task['execution_task_id']})."

    async def close_all_sessions(self) -> None:
        """End all open agent sessions (writes memory, closes logs)."""
        for session in self._session_cache.values():
            with contextlib.suppress(Exception):
                await session.end_session()
        self._session_cache.clear()
