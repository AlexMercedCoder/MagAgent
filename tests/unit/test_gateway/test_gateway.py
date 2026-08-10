"""Unit tests for gateway router — no real platform connections needed."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from magent.gateway.base import IncomingMessage, OutgoingMessage
from magent.gateway.router import MessageRouter, RateLimiter

# ─────────────────────────────────────────────
# RateLimiter tests
# ─────────────────────────────────────────────


class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(max_per_minute=5)
        for _ in range(5):
            assert rl.is_allowed("user1") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_per_minute=3)
        for _ in range(3):
            rl.is_allowed("user1")
        assert rl.is_allowed("user1") is False

    def test_different_users_independent(self):
        rl = RateLimiter(max_per_minute=2)
        rl.is_allowed("user1")
        rl.is_allowed("user1")
        assert rl.is_allowed("user1") is False
        # user2 is independent
        assert rl.is_allowed("user2") is True

    def test_seconds_until_reset_zero_when_empty(self):
        rl = RateLimiter(max_per_minute=5)
        assert rl.seconds_until_reset("user1") == 0.0

    def test_seconds_until_reset_positive_after_use(self):
        rl = RateLimiter(max_per_minute=1)
        rl.is_allowed("user1")
        rl.is_allowed("user1")  # blocked
        seconds = rl.seconds_until_reset("user1")
        assert 0 < seconds <= 60


# ─────────────────────────────────────────────
# MessageRouter auth tests
# ─────────────────────────────────────────────


def _make_msg(**kwargs) -> IncomingMessage:
    defaults = dict(
        platform="test",
        message_id="msg1",
        user_id="user123",
        username="Alice",
        channel_id="chan1",
        text="hello agent",
        is_dm=True,
    )
    defaults.update(kwargs)
    return IncomingMessage(**defaults)


class TestMessageRouterAuth:
    def _router(self, **cfg):
        # Tests that are not about the allowlist itself opt in explicitly,
        # because an empty allowlist now means "admit nobody".
        config = {"username": "testuser", "allow_anyone": True, **cfg}
        return MessageRouter(config)

    def test_blocks_everyone_when_allowlist_is_empty(self):
        """Fail closed: an empty allowlist used to admit the whole workspace
        to a headless session where permission checks auto-resolve."""
        router = MessageRouter({"username": "testuser"})
        allowed, reason = router.is_authorized(_make_msg())
        assert allowed is False
        assert "allowlist is empty" in reason

    def test_allow_anyone_is_an_explicit_opt_in(self):
        router = MessageRouter({"username": "testuser", "allow_anyone": True})
        allowed, _ = router.is_authorized(_make_msg())
        assert allowed is True

    def test_blocks_user_not_in_allowlist(self):
        router = self._router(allowed_user_ids=["user999"])
        msg = _make_msg(user_id="user123")
        allowed, reason = router.is_authorized(msg)
        assert allowed is False
        assert "not in allowlist" in reason

    def test_allows_user_in_allowlist(self):
        router = self._router(allowed_user_ids=["user123", "user456"])
        msg = _make_msg(user_id="user123")
        allowed, _ = router.is_authorized(msg)
        assert allowed is True

    def test_blocks_channel_not_in_allowlist(self):
        router = self._router(allowed_channel_ids=["chan999"])
        msg = _make_msg(channel_id="chan1")
        allowed, reason = router.is_authorized(msg)
        assert allowed is False
        assert "Channel" in reason

    def test_allows_channel_in_allowlist(self):
        router = self._router(allowed_channel_ids=["chan1", "chan2"])
        msg = _make_msg(channel_id="chan1")
        allowed, _ = router.is_authorized(msg)
        assert allowed is True

    def test_rate_limit_blocks_after_threshold(self):
        router = self._router(rate_limit_per_minute=2)
        msg = _make_msg()
        router.is_authorized(msg)
        router.is_authorized(msg)
        allowed, reason = router.is_authorized(msg)
        assert allowed is False
        assert "Rate limit" in reason

    def test_both_allowlists_must_pass(self):
        router = self._router(
            allowed_user_ids=["user123"],
            allowed_channel_ids=["chan999"],
        )
        msg = _make_msg(user_id="user123", channel_id="chan1")
        allowed, _ = router.is_authorized(msg)
        assert allowed is False  # user OK but channel blocked


class TestMessageRouterHandle:
    @pytest.mark.asyncio
    async def test_returns_auth_error_for_blocked_user(self):
        router = MessageRouter({"username": "testuser", "allowed_user_ids": ["other_user"]})
        msg = _make_msg(user_id="blocked_user")
        result = await router.handle(msg)
        assert "⛔" in result

    @pytest.mark.asyncio
    async def test_dispatches_to_session_on_auth_pass(self, tmp_path, monkeypatch):
        import magent.workbench_store as workbench_store

        monkeypatch.setattr(workbench_store, "USERS_DIR", tmp_path / "users")
        router = MessageRouter({"username": "testuser", "allow_anyone": True})
        # Mock the session so we don't need a real LLM
        mock_session = AsyncMock()
        mock_session.chat = AsyncMock(return_value="Hello from agent!")
        mock_session.session_id = "gateway-session"
        mock_session.cwd = str(tmp_path)
        mock_session.provider = MagicMock(provider_id="test", model="test")
        mock_session.logger = None
        mock_session.scratchpad = {}
        mock_session.turn_count = 1
        router._session_cache["chan1"] = mock_session

        msg = _make_msg()
        result = await router.handle(msg)
        assert result == "Hello from agent!"
        mock_session.chat.assert_called_once_with("hello agent")

    @pytest.mark.asyncio
    async def test_gateway_session_approval_adds_exact_command(self):
        router = MessageRouter({"username": "testuser", "allow_anyone": True})
        mock_session = MagicMock()
        mock_session.tools.session_shell_patterns = []
        router._session_cache["chan1"] = mock_session

        msg = _make_msg(text="/approve session npm install")
        result = await router.handle(msg)

        assert "Approved for this gateway session" in result
        assert mock_session.tools.session_shell_patterns == ["npm install"]

    @pytest.mark.asyncio
    async def test_returns_error_string_on_session_exception(self, tmp_path, monkeypatch):
        import magent.workbench_store as workbench_store

        monkeypatch.setattr(workbench_store, "USERS_DIR", tmp_path / "users")
        router = MessageRouter({"username": "testuser", "allow_anyone": True})
        mock_session = AsyncMock()
        mock_session.chat = AsyncMock(side_effect=RuntimeError("LLM exploded"))
        mock_session.session_id = "gateway-session"
        mock_session.cwd = str(tmp_path)
        mock_session.provider = MagicMock(provider_id="test", model="test")
        mock_session.logger = None
        mock_session.scratchpad = {}
        mock_session.turn_count = 1
        router._session_cache["chan1"] = mock_session

        msg = _make_msg()
        result = await router.handle(msg)
        assert "❌" in result
        # Provider exception strings can carry request URLs, headers and keys,
        # so the remote user gets a type and a reference, not the detail.
        assert "LLM exploded" not in result
        assert "RuntimeError" in result
        assert "ref " in result


# ─────────────────────────────────────────────
# Base adapter ack_and_respond flow tests
# ─────────────────────────────────────────────


class ConcreteAdapter:
    """Minimal concrete GatewayAdapter for testing the base flow."""

    def __init__(self):
        self.posted: list[OutgoingMessage] = []
        self.updated: list[tuple] = []
        self.typing_sent: list[str] = []
        self.config = {"max_task_duration_seconds": 10}
        self.platform_name = "test"

    async def post_message(self, msg: OutgoingMessage) -> str | None:
        self.posted.append(msg)
        return "msg_id_123"

    async def update_message(self, channel_id: str, message_id: str, new_text: str) -> None:
        self.updated.append((channel_id, message_id, new_text))

    async def send_typing(self, channel_id: str) -> None:
        self.typing_sent.append(channel_id)

    async def handler(self, msg: IncomingMessage) -> str:
        return f"Agent reply to: {msg.text}"

    # Import and bind the base method
    ack_and_respond = __import__(
        "magent.gateway.base", fromlist=["GatewayAdapter"]
    ).GatewayAdapter.ack_and_respond


class TestAckAndRespond:
    @pytest.mark.asyncio
    async def test_posts_ack_then_updates_with_result(self):
        from magent.gateway.base import GatewayAdapter

        adapter = MagicMock(spec=GatewayAdapter)
        adapter.config = {"max_task_duration_seconds": 10}
        adapter.platform_name = "test"
        adapter.post_message = AsyncMock(return_value="ack_id")
        adapter.update_message = AsyncMock()
        adapter.send_typing = AsyncMock()
        adapter.handler = AsyncMock(return_value="Done! Here is your answer.")

        msg = _make_msg()
        await GatewayAdapter.ack_and_respond(adapter, msg)

        # Should post ack immediately
        assert adapter.post_message.call_count == 1
        ack_call = adapter.post_message.call_args[0][0]
        assert "Working" in ack_call.text

        # Should update with result
        adapter.update_message.assert_called_once()
        _, _, updated_text = adapter.update_message.call_args[0]
        assert "Done!" in updated_text

    @pytest.mark.asyncio
    async def test_handles_agent_timeout(self):
        from magent.gateway.base import GatewayAdapter

        adapter = MagicMock(spec=GatewayAdapter)
        adapter.config = {"max_task_duration_seconds": 0}  # immediate timeout
        adapter.platform_name = "test"
        adapter.post_message = AsyncMock(return_value="ack_id")
        adapter.update_message = AsyncMock()
        adapter.send_typing = AsyncMock()

        async def slow_handler(msg):
            await asyncio.sleep(100)
            return "never"

        adapter.handler = slow_handler

        msg = _make_msg()
        await GatewayAdapter.ack_and_respond(adapter, msg)

        _, _, updated_text = adapter.update_message.call_args[0]
        assert "timed out" in updated_text.lower()

    @pytest.mark.asyncio
    async def test_posts_followup_when_no_ack_id(self):
        """If post_message returns None (post failed), send a new message instead of edit."""
        from magent.gateway.base import GatewayAdapter

        adapter = MagicMock(spec=GatewayAdapter)
        adapter.config = {"max_task_duration_seconds": 10}
        adapter.platform_name = "test"
        adapter.post_message = AsyncMock(return_value=None)  # ack post failed
        adapter.update_message = AsyncMock()
        adapter.send_typing = AsyncMock()
        adapter.handler = AsyncMock(return_value="Result text")

        msg = _make_msg()
        await GatewayAdapter.ack_and_respond(adapter, msg)

        # Should post twice (ack + result), not try to edit
        assert adapter.post_message.call_count == 2
        adapter.update_message.assert_not_called()


# ─────────────────────────────────────────────
# Adapter utility function tests
# ─────────────────────────────────────────────


class TestSlackUtils:
    def test_truncate_under_limit_unchanged(self):
        from magent.gateway.adapters.slack import _truncate_slack

        text = "short message"
        assert _truncate_slack(text) == text

    def test_truncate_over_limit_adds_notice(self):
        from magent.gateway.adapters.slack import _truncate_slack

        long_text = "x" * 4000
        result = _truncate_slack(long_text, max_len=100)
        assert len(result) < 4000
        assert "truncated" in result.lower()


class TestDiscordUtils:
    def test_chunk_short_message_single_chunk(self):
        from magent.gateway.adapters.discord import _chunk_discord

        text = "Hello world"
        assert _chunk_discord(text) == [text]

    def test_chunk_long_message_multiple_chunks(self):
        from magent.gateway.adapters.discord import _chunk_discord

        text = "line\n" * 500
        chunks = _chunk_discord(text, max_len=100)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 100

    def test_chunk_reassembles_to_original(self):
        from magent.gateway.adapters.discord import _chunk_discord

        text = "abc\ndef\nghi\njkl\n" * 50
        chunks = _chunk_discord(text, max_len=60)
        reassembled = "\n".join(c.strip("\n") for c in chunks)
        # All content should be preserved
        assert "abc" in reassembled
        assert "jkl" in reassembled


class TestTelegramUtils:
    def test_chunk_short_message_single_chunk(self):
        from magent.gateway.adapters.telegram import _chunk_telegram

        text = "Short message"
        assert _chunk_telegram(text) == [text]

    def test_chunk_long_message(self):
        from magent.gateway.adapters.telegram import _chunk_telegram

        text = "word " * 1000
        chunks = _chunk_telegram(text, max_len=200)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 200


# ─────────────────────────────────────────────
# Gateway hardening regressions
# ─────────────────────────────────────────────


class TestGatewayHardening:
    def test_persistent_approvals_are_off_by_default(self):
        """`/approve always` writes into the on-disk profile, where it also
        applies to future local CLI sessions."""
        router = MessageRouter({"username": "testuser", "allow_anyone": True})
        result = router._handle_approval_command(_make_msg(text="/approve always rm -rf /tmp/x"))
        assert "disabled" in result

    def test_persistent_approvals_can_be_limited_to_admins(self):
        router = MessageRouter(
            {
                "username": "testuser",
                "allow_anyone": True,
                "allow_persistent_approvals": True,
                "admin_user_ids": ["someone_else"],
            }
        )
        result = router._handle_approval_command(_make_msg(text="/approve always npm test"))
        assert "admins" in result

    def test_require_mention_gates_group_messages(self):
        from magent.gateway.base import GatewayAdapter

        class Adapter(GatewayAdapter):
            platform_name = "test"

            async def start(self): ...
            async def stop(self): ...
            async def post_message(self, msg): ...
            async def update_message(self, channel_id, message_id, new_text): ...
            async def send_typing(self, channel_id): ...

        adapter = Adapter({"require_mention": True}, AsyncMock())

        assert adapter.should_respond(_make_msg(is_dm=True)) is True
        assert adapter.should_respond(_make_msg(is_dm=False, mentions_bot=True)) is True
        assert adapter.should_respond(_make_msg(is_dm=False, mentions_bot=False)) is False

    def test_rate_limiter_reset_lookup_does_not_create_entries(self):
        limiter = RateLimiter(max_per_minute=5)
        limiter.seconds_until_reset("never-seen")
        assert "never-seen" not in limiter._buckets

    def test_rate_limiter_prunes_expired_users(self):
        limiter = RateLimiter(max_per_minute=5)
        limiter.is_allowed("old-user")
        limiter._buckets["old-user"] = [0.0]  # long expired
        limiter.is_allowed("new-user")
        assert "old-user" not in limiter._buckets

    @pytest.mark.asyncio
    async def test_channel_messages_are_serialised(self, tmp_path, monkeypatch):
        """One AgentSession per channel entered concurrently corrupts its
        conversation and scratchpad."""
        import magent.workbench_store as workbench_store

        monkeypatch.setattr(workbench_store, "USERS_DIR", tmp_path / "users")
        router = MessageRouter({"username": "testuser", "allow_anyone": True})

        concurrent = 0
        peak = 0

        async def chat(text):
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1
            return "ok"

        mock_session = AsyncMock()
        mock_session.chat = chat
        mock_session.session_id = "gateway-session"
        mock_session.cwd = str(tmp_path)
        mock_session.provider = MagicMock(provider_id="test", model="test")
        mock_session.logger = None
        mock_session.scratchpad = {}
        mock_session.turn_count = 1
        router._session_cache["chan1"] = mock_session

        await asyncio.gather(*(router.handle(_make_msg()) for _ in range(4)))
        assert peak == 1


class TestSecretScrubbing:
    def test_keys_are_scrubbed(self):
        from magent.secret_scrub import scrub_secrets

        scrubbed = scrub_secrets("failed with api_key=abcdef1234567890 and sk-abcdefghijklmnopqrst")
        assert "abcdef1234567890" not in scrubbed
        assert "sk-abcdefghijklmnopqrst" not in scrubbed

    def test_safe_error_message_hides_detail(self):
        from magent.secret_scrub import safe_error_message

        message = safe_error_message(RuntimeError("Bearer sk-verysecrettoken12345 rejected"))
        assert "sk-verysecrettoken12345" not in message
        assert "RuntimeError" in message
