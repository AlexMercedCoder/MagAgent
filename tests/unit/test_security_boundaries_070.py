from __future__ import annotations

import ipaddress
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magent.gateway.base import IncomingMessage
from magent.gateway.router import MessageRouter
from magent.net_policy import (
    UrlPolicyError,
    classify_network_action,
    read_capped,
    request_with_policy,
    validate_request_url,
)
from magent.permissions import RiskTier


def message(text: str = "hello", **updates) -> IncomingMessage:
    values = {
        "platform": "test",
        "message_id": "m1",
        "user_id": "u1",
        "username": "Alex",
        "channel_id": "c1",
        "text": text,
        "is_dm": True,
    }
    values.update(updates)
    return IncomingMessage(**values)


@pytest.mark.parametrize(
    "url",
    ["", "ftp://example.com/file", "http:///missing", "http://example.com:bad/"],
)
def test_url_validation_rejects_malformed_inputs(url: str) -> None:
    with pytest.raises(UrlPolicyError):
        validate_request_url(url)


def test_url_policy_private_opt_in_and_method_tiers() -> None:
    assert validate_request_url("http://127.0.0.1/dev", allow_private=True).endswith("/dev")
    assert classify_network_action("GET", "https://example.com") == RiskTier.AUTO
    assert classify_network_action("post", "https://example.com") == RiskTier.CONFIRM


class FakeResponse:
    def __init__(self, *, status: int = 200, location: str = "", chunks=()):
        self.status_code = status
        self.is_redirect = 300 <= status < 400
        self.headers = {"location": location} if location else {}
        self.encoding = "utf-8"
        self._chunks = list(chunks)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def build_request(self, method, url, **kwargs):
        request = SimpleNamespace(method=method, url=url, kwargs=kwargs)
        self.requests.append(request)
        return request

    async def send(self, request, **kwargs):
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_redirects_are_revalidated_and_303_drops_body(monkeypatch) -> None:
    monkeypatch.setattr("magent.net_policy._resolve", lambda *_: [])
    first = FakeResponse(status=303, location="/done")
    final = FakeResponse(chunks=[b"ok"])
    client = FakeClient([first, final])

    response = await request_with_policy(
        client,
        "POST",
        "https://example.com/start",
        json={"value": 1},
    )

    assert response is final
    assert [request.method for request in client.requests] == ["POST", "GET"]
    assert "json" not in client.requests[1].kwargs
    assert first.closed is True


@pytest.mark.asyncio
async def test_redirect_to_private_address_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        "magent.net_policy._resolve",
        lambda host, _port: (
            [ipaddress.ip_address("127.0.0.1")] if host == "127.0.0.1" else []
        ),
    )
    client = FakeClient([FakeResponse(status=302, location="http://127.0.0.1/admin")])

    with pytest.raises(UrlPolicyError):
        await request_with_policy(client, "GET", "https://example.com/start")


@pytest.mark.asyncio
async def test_response_reader_caps_and_closes() -> None:
    response = FakeResponse(chunks=[b"abc", b"def"])
    assert await read_capped(response, limit=4) == "abcd"
    assert response.closed is True


def test_gateway_approval_scope_and_operator_controls(monkeypatch) -> None:
    router = MessageRouter({"username": "test", "allow_anyone": True})
    session = SimpleNamespace(
        session_id="s1",
        turn_count=2,
        cwd="/project",
        tools=SimpleNamespace(session_shell_patterns=[], trusted_shell_patterns=[]),
    )
    router._session_cache["c1"] = session

    assert router._handle_approval_command(message("hello")) is None
    assert "Usage" in router._handle_approval_command(message("/approve bad"))
    assert "Approved" in router._handle_approval_command(message("/approve session pytest -q"))
    assert session.tools.session_shell_patterns == ["pytest -q"]
    assert router.session_report()["sessions"][0]["session_id"] == "s1"
    assert router.revoke_user("nobody")["allow_anyone"] is False
    assert router.revoke_user("nobody")["ok"] is False


@pytest.mark.asyncio
async def test_gateway_session_end_and_close() -> None:
    router = MessageRouter({"username": "test", "allow_anyone": True})
    first = SimpleNamespace(end_session=AsyncMock())
    second = SimpleNamespace(end_session=AsyncMock())
    router._session_cache.update({"one": first, "two": second})

    assert (await router.end_session("missing"))["ok"] is False
    assert (await router.end_session("one"))["ok"] is True
    first.end_session.assert_awaited_once()
    await router.close_all_sessions()
    second.end_session.assert_awaited_once()
    assert router._session_cache == {}


def test_gateway_graph_path_containment_and_parse_errors(tmp_path) -> None:
    router = MessageRouter(
        {"username": "test", "allow_anyone": True, "project": str(tmp_path)}
    )

    assert router._handle_graph_command(message("hello")) is None
    assert "Invalid" in router._handle_graph_command(message('/graph plan "unterminated'))
    assert "Usage" in router._handle_graph_command(message("/graph nope graph.yaml"))
    assert "stay inside" in router._handle_graph_command(message("/graph run ../escape.yaml"))


@pytest.mark.asyncio
async def test_gateway_errors_are_safe_for_remote_chat(monkeypatch) -> None:
    router = MessageRouter({"username": "test", "allow_anyone": True})
    monkeypatch.setattr(
        router,
        "_get_session",
        lambda _: (_ for _ in ()).throw(RuntimeError("Authorization: Bearer sk-secretsecretsecretsecret")),
    )

    result = await router.handle(message())

    assert "secretsecret" not in result
    assert "ref " in result
