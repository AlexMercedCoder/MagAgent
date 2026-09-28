"""G-6: `magent serve --rpc` (magent.rpc.v1)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from magent.rpc_gateway import (
    FORBIDDEN,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    NOT_FOUND,
    UNAUTHORIZED,
    Gateway,
    redact_args,
    serve_rpc,
)

TOKEN = "t" * 32
AUTH = f"Bearer {TOKEN}"

# A stand-in for `python -m magent` that behaves like an approval-gated run:
# print a line, emit an AAIS request, wait for a decision on stdin, echo it.
FAKE = r"""
import json, sys, time
args = sys.argv[1:]
if args[:1] == ["sleep"]:
    print("sleeping", flush=True); time.sleep(60)
elif args[:1] == ["approve"]:
    print(json.dumps({"type": "approval.requested", "request": {"id": "apr_1"}}), flush=True)
    line = sys.stdin.readline()
    print("decided:" + json.loads(line)["decision"]["decision"], flush=True)
elif args[:1] == ["echo-input"]:
    print(sys.stdin.read().upper(), end="")
else:
    print("args:" + " ".join(args)); print("warn", file=sys.stderr); sys.exit(3 if "fail" in args else 0)
"""


def fake_command() -> list[str]:
    return [sys.executable, "-c", FAKE]


@pytest.fixture
def gateway(tmp_path: Path) -> Gateway:
    gw = Gateway(
        token=TOKEN, roots=[tmp_path], audit_path=tmp_path / "audit.jsonl", command=fake_command
    )
    yield gw
    gw.shutdown()


def call(gw: Gateway, method: str, params: dict | None = None, auth: str = AUTH) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": method, "params": params or {}})
    return gw.handle(body.encode(), auth)


def test_token_is_required_and_compared_exactly(gateway: Gateway) -> None:
    assert call(gateway, "runtime_info", auth="")["error"]["code"] == UNAUTHORIZED
    assert call(gateway, "runtime_info", auth="Bearer wrong")["error"]["code"] == UNAUTHORIZED
    info = call(gateway, "runtime_info")["result"]
    assert info["protocol"] == "magent.rpc.v1"
    assert "stream.start" in info["methods"] and "write_magent_stream" in info["methods"]


def test_short_tokens_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Gateway(token="short", roots=[tmp_path])


def test_request_response_commands_match_the_native_result_shape(gateway: Gateway) -> None:
    result = call(gateway, "run_magent", {"args": ["status", "--json"]})["result"]
    assert set(result) == {"ok", "command", "stdout", "stderr", "status"}
    assert result["ok"] is True and "args:status --json" in result["stdout"]
    failed = call(gateway, "run_magent", {"args": ["fail"]})["result"]
    assert failed["ok"] is False and failed["status"] == 3
    echoed = call(gateway, "run_magent_input", {"args": ["echo-input"], "input": "hi"})["result"]
    assert echoed["stdout"] == "HI"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"args": "ask hi"}, INVALID_PARAMS),
        ({"args": ["serve", "--rpc"]}, FORBIDDEN),
        ({"args": ["ui"]}, FORBIDDEN),
        ({"args": ["daemon", "start"]}, FORBIDDEN),
        ({"args": ["ask", "x", "--project", "/"]}, FORBIDDEN),
        ({"args": ["ask", "x", "--project=../.."]}, FORBIDDEN),
        ({"args": ["x" * 70_000]}, INVALID_PARAMS),
    ],
)
def test_arguments_are_validated(gateway: Gateway, params: dict, code: int) -> None:
    assert call(gateway, "run_magent", params)["error"]["code"] == code


def test_unknown_methods_and_bad_json(gateway: Gateway) -> None:
    error = call(gateway, "inspect_project", {"path": "/"})["error"]
    assert error["code"] == METHOD_NOT_FOUND and "run_magent" in error["data"]["methods"]
    assert gateway.handle(b"{not json", AUTH)["error"]["code"] == -32700
    assert gateway.handle(b"[]", AUTH)["error"]["code"] == -32600


def test_stream_lifecycle_with_approval(gateway: Gateway) -> None:
    started = call(gateway, "stream.start", {"id": "run-1", "args": ["approve"]})["result"]
    assert started["id"] == "run-1"
    page = {"events": [], "next": 0}
    deadline = time.monotonic() + 20
    seen: list[dict] = []
    while time.monotonic() < deadline and not any("approval.requested" in e["line"] for e in seen):
        page = call(
            gateway, "stream.events", {"id": "run-1", "after": page["next"], "wait_ms": 2000}
        )["result"]
        seen.extend(page["events"])
    assert seen[0]["stream"] == "status"
    decision = {
        "aais": "1.0",
        "type": "approval.decided",
        "id": "evt_1",
        "occurred_at": "2026-09-27T00:00:00Z",
        "sequence": 1,
        "decision": {
            "id": "dec_1",
            "request_id": "apr_1",
            "action_digest": "sha256:" + "0" * 64,
            "decided_at": "2026-09-27T00:00:00Z",
            "decision": "approve",
            "scope": "once",
            "actor": {"id": "alex", "type": "human"},
        },
    }
    assert (
        call(gateway, "write_magent_stream", {"id": "run-1", "line": json.dumps(decision)})[
            "result"
        ]
        is True
    )
    while time.monotonic() < deadline and not page["done"]:
        page = call(
            gateway, "stream.events", {"id": "run-1", "after": page["next"], "wait_ms": 2000}
        )["result"]
        seen.extend(page["events"])
    assert page["done"] and page["result"]["ok"] is True
    assert any(e["line"] == "decided:approve" for e in seen)
    assert seen[-1]["line"] == "MagAgent process completed"
    listed = call(gateway, "stream.list")["result"]["streams"]
    assert listed[0]["id"] == "run-1" and listed[0]["done"] is True


def test_only_decisions_may_be_written(gateway: Gateway) -> None:
    call(gateway, "stream.start", {"id": "run-2", "args": ["sleep"]})
    bad = call(gateway, "write_magent_stream", {"id": "run-2", "line": '{"type": "x"}'})
    assert bad["error"]["code"] == INVALID_PARAMS
    assert call(gateway, "cancel_magent_stream", {"id": "run-2"})["result"] is True


def test_cancel_stops_the_run_and_its_children(gateway: Gateway) -> None:
    call(gateway, "stream.start", {"id": "run-3", "args": ["sleep"]})
    assert call(gateway, "cancel_magent_stream", {"id": "run-3"})["result"] is True
    page = call(gateway, "stream.events", {"id": "run-3", "after": 0, "wait_ms": 10000})["result"]
    deadline = time.monotonic() + 15
    while not page["done"] and time.monotonic() < deadline:
        page = call(
            gateway, "stream.events", {"id": "run-3", "after": page["next"], "wait_ms": 2000}
        )["result"]
    assert page["done"] and page["result"]["ok"] is False
    assert call(gateway, "cancel_magent_stream", {"id": "run-3"})["result"] is False
    assert call(gateway, "stream.events", {"id": "nope"})["error"]["code"] == NOT_FOUND


def test_audit_log_redacts_secrets(gateway: Gateway, tmp_path: Path) -> None:
    call(gateway, "run_magent", {"args": ["auth", "add", "openai", "--api-key", "sk-secret"]})
    log = (tmp_path / "audit.jsonl").read_text()
    assert "sk-secret" not in log and "<redacted>" in log
    assert redact_args(["--token=abc", "x"]) == ["--token=<redacted>", "x"]


def _post(url: str, method: str, params: dict, token: str = TOKEN) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 7, "method": method, "params": params}).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        # Close the error's response body: Python 3.14 reports an unclosed one
        # as a ResourceWarning, which pytest turns into a failure.
        with error:
            return error.code, json.loads(error.read())


def test_http_server_end_to_end_with_the_mock_provider(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from magent.cli import main as cli_main

    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "rpc"]).exit_code == 0
    for key, value in (
        ("memory.extraction_provider", "mock"),
        ("memory.semantic_enabled", "false"),
    ):
        assert runner.invoke(cli_main.app, ["config", "set", key, value]).exit_code == 0

    with pytest.raises(ValueError, match="TLS"):
        serve_rpc(host="0.0.0.0", port=0, token=TOKEN, roots=[tmp_path])
    server, gateway, info = serve_rpc(port=0, token=TOKEN, roots=[tmp_path])
    try:
        url = info["url"]
        with urllib.request.urlopen(url.replace("/rpc", "/healthz"), timeout=10) as response:
            assert json.loads(response.read())["ok"] is True
        status, denied = _post(url, "runtime_info", {}, token="x" * 20)
        assert status == 401 and denied["error"]["code"] == UNAUTHORIZED
        status, body = _post(
            url,
            "stream.start",
            {"id": "ask-1", "args": ["ask", "hello gateway", "--provider", "mock", "--json"]},
        )
        assert status == 200, body
        request = urllib.request.Request(
            url.replace("/rpc", "/rpc/streams/ask-1/events") + "?after=0",
            headers={"authorization": AUTH},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            assert response.headers["content-type"] == "text/event-stream"
            text = response.read().decode()
        assert "event: stream" in text and "event: done" in text
        done = json.loads(text.split("event: done\ndata: ", 1)[1].split("\n", 1)[0])
        assert done["ok"] is True
        payload = json.loads(done["stdout"])
        assert payload["response"].startswith("[MagAgent mock provider")
    finally:
        gateway.shutdown()
        server.shutdown()
        server.server_close()


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rpc_gateway" / "lifecycle.json"


def _shape(value):
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return type(value).__name__


def test_recorded_lifecycle_fixtures_match_the_live_gateway(gateway: Gateway) -> None:
    document = json.loads(FIXTURES.read_text())
    assert document["protocol"] == "magent.rpc.v1"
    for exchange in document["exchanges"]:
        request, recorded = exchange["request"], exchange["response"]
        assert recorded["jsonrpc"] == "2.0"
        assert ("result" in recorded) != ("error" in recorded)
        if exchange["name"] in {
            "runtime_info",
            "unauthorized",
            "run_magent",
            "run_magent_input",
            "forbidden_command",
            "project_outside_roots",
            "unknown_method",
            "unknown_stream",
        }:
            auth = AUTH if exchange["authorization"] == "Bearer <token>" else "Bearer wrong"
            live = gateway.handle(json.dumps(request).encode(), auth)
            assert _shape(live) == _shape(recorded), exchange["name"]
            if "error" in recorded:
                assert live["error"]["code"] == recorded["error"]["code"]
