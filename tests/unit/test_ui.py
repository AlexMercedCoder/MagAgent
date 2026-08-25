from __future__ import annotations

import http.client
import json
import re
from pathlib import Path

import pytest

import magent.ui as ui_module
from magent import workbench
from magent.ui import STATIC_DIR, render_ui_html, serve_ui, ui_state
from magent.workbench import WorkbenchStore


def test_ui_state_collects_local_workbench_data(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-test")
    store.append("tasks", {"title": "Draft release notes", "status": "open"})
    store.append("patches", {"name": "docs.patch", "path": str(project / "docs.patch")})

    state = ui_state(store, project=project, username=None)

    assert state["ok"] is True
    assert state["project"] == str(project.resolve())
    assert len(state["tasks"]) == 1
    assert state["workspace"]["patches"] == 1
    assert state["memory_quality"]["ok"] is False
    assert state["model_health"]["ok"] is True
    assert state["readiness"] is None
    assert any(topic["slug"] == "ui" for topic in state["docs"])
    assert state["cockpit"]["release_check"]["status"] == "not_run"


def test_ui_state_does_not_execute_release_check(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-test")

    def fail_release_check(*args, **kwargs):
        raise AssertionError("release checks should be explicit, not part of UI state")

    monkeypatch.setattr(workbench, "_run_command_args", fail_release_check)

    state = ui_state(store, project=project, username=None)

    assert state["ok"] is True
    assert state["cockpit"]["release_check"]["command"] == "magent release check"


def test_render_ui_html_is_the_spa_shell() -> None:
    """The shell boots the bundle; the views themselves live in the bundle.

    Before the TypeScript port the markup for every view was written by hand
    into this file, so it could be asserted directly. It is now a Vite entry
    point, and what matters is that it mounts and references built assets.
    """
    html = render_ui_html()

    assert "<title>MagAgent</title>" in html
    assert 'id="root"' in html
    # Hashed, so a stale or missing build shows up as a broken reference.
    assert re.search(r'src="/assets/index-[\w-]+\.js"', html)
    assert re.search(r'href="/assets/index-[\w-]+\.css"', html)
    # The theme stamp must stay a separate file: the CSP forbids inline script.
    assert 'src="/theme-init.js"' in html
    assert "<script>" not in html


def test_bundle_carries_every_view() -> None:
    """A build that dropped a view would still serve a valid shell."""
    bundle = next((STATIC_DIR / "assets").glob("index-*.js")).read_text(encoding="utf-8")

    for heading in ("Graph Kanban", "Your bots", "Operations", "Profiles", "Settings"):
        assert heading in bundle, heading



def test_ui_action_helpers_use_domain_modules(tmp_path: Path, monkeypatch) -> None:
    from magent import ui_actions

    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-test")
    store.append("tasks", {"title": "Promote from UI", "status": "open"})
    patch = store.append("patches", {"name": "demo", "path": str(tmp_path / "demo.patch")})
    (tmp_path / "demo.patch").write_text("diff --git a/a b/a\n+++ b/a\n+new\n", encoding="utf-8")

    release = ui_actions.run_release_check(store, tmp_path)
    inbox = ui_actions.list_memory_inbox(store, tmp_path)
    patch_preview = ui_actions.inspect_patch(store, patch["id"])

    assert "ok" in release
    assert inbox["candidates"][0]["source"] == "task"
    assert patch_preview["stats"]["added"] == 1


def test_serve_ui_serves_html_and_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-test")
    started = {"ok": False}

    class FakeServer:
        def __init__(self, address, handler):
            self.address = address
            self.handler = handler

        def serve_forever(self):
            started["ok"] = True

    class FakeThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    monkeypatch.setattr(ui_module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(ui_module.threading, "Thread", FakeThread)

    result = serve_ui(store, project=tmp_path, username=None, port=7831, open_browser=False)

    assert result["ok"] is True
    assert result["project"] == str(tmp_path.resolve())
    assert started["ok"] is True

    # Loopback binding is not access control: any page the user visits can call
    # 127.0.0.1. Every request needs the per-launch token, which travels in the
    # URL the caller is handed.
    assert result["token"]
    assert result["url"] == f"http://127.0.0.1:7831/?token={result['token']}"
    # The server handle is returned so callers can shut it down.
    assert result["server"] is not None


def test_live_ui_auth_csrf_and_conversation_api(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-http-test")
    result = serve_ui(store, project=tmp_path, username=None, port=0, open_browser=False)
    if not result["ok"] and "Operation not permitted" in result.get("error", ""):
        pytest.skip("local socket binding is disabled by the test sandbox")
    assert result["ok"] is True
    server = result["server"]
    port = server.server_address[1]
    token = result["token"]

    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/api/bootstrap")
        assert connection.getresponse().status == 403

        # Listing conversations is a safe read and must succeed. The GET branch
        # for this path existed but was unreachable: the blanket "mutating
        # paths refuse GET" guard caught it too, so every list request 405'd.
        connection.request("GET", f"/api/conversations?token={token}")
        listing = connection.getresponse()
        assert listing.status == 200
        assert json.loads(listing.read())["ok"] is True

        # Paths that only have a write handler must still refuse GET, or the
        # request would fall through into that handler.
        for write_only in ("/api/settings", "/api/profiles", "/api/graphs/run"):
            connection.request("GET", f"{write_only}?token={token}")
            assert connection.getresponse().status == 405, write_only

        connection.request(
            "POST",
            f"/api/conversations?token={token}",
            body='{"kind":"chat","title":"HTTP test"}',
            headers={"Content-Type": "application/json", "X-Magent-CSRF": "wrong"},
        )
        assert connection.getresponse().status == 403

        connection.request(
            "POST",
            f"/api/conversations?token={token}",
            body='{"kind":"chat","title":"HTTP test"}',
            headers={"Content-Type": "application/json", "X-Magent-CSRF": token},
        )
        response = connection.getresponse()
        assert response.status == 201
        assert b'"title": "HTTP test"' in response.read()
    finally:
        server.shutdown()
        server.server_close()


def test_a_turn_survives_the_browser_that_asked_for_it(tmp_path: Path, monkeypatch) -> None:
    """The turn used to run on the request thread that started it.

    Close the tab mid-reply and the work died with the socket: the assistant's
    answer was never recorded and the conversation kept a question with no
    response. A turn is now a run, and it finishes whether or not anyone is
    watching.
    """
    import threading
    import time

    from magent import ui as ui_module

    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-run-test")

    replied = threading.Event()

    class SlowRunner:
        """Stands in for the model: slow enough to abandon mid-reply."""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, _conversation, _prompt, *, on_chunk=None, should_continue=None):
            for piece in ("thinking", " ", "done"):
                if should_continue:
                    should_continue()
                if on_chunk:
                    on_chunk("MagAgent", piece)
                time.sleep(0.3)
            replied.set()
            return [{"content": "thinking done", "speaker": "MagAgent"}]

    import magent.web_chat as web_chat

    monkeypatch.setattr(web_chat, "WebChatRunner", SlowRunner)

    result = ui_module.serve_ui(
        store, project=tmp_path, username="ui-run-test", port=0, open_browser=False
    )
    if not result["ok"] and "Operation not permitted" in result.get("error", ""):
        pytest.skip("local socket binding is disabled by the test sandbox")
    server = result["server"]
    port = server.server_address[1]
    token = result["token"]
    write_headers = {"Content-Type": "application/json", "X-Magent-CSRF": token}

    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            f"/api/conversations?token={token}",
            body='{"kind":"chat","title":"Durable"}',
            headers=write_headers,
        )
        conversation_id = json.loads(connection.getresponse().read())["conversation"]["id"]

        # Start the turn, read one line, then hang up mid-reply.
        talker = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        talker.request(
            "POST",
            f"/api/conversations/message?token={token}",
            body=json.dumps({"conversation_id": conversation_id, "content": "hello"}),
            headers=write_headers,
        )
        stream = talker.getresponse()
        first = json.loads(stream.fp.readline())
        assert first["type"] == "run"
        run_id = first["id"]
        talker.close()

        # The abandoned turn must still finish and record its answer.
        assert replied.wait(10), "the run died with the socket that started it"

        listing = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        deadline = time.monotonic() + 10
        messages: list[dict] = []
        while time.monotonic() < deadline:
            listing.request("GET", f"/api/conversations?token={token}")
            found = json.loads(listing.getresponse().read())["conversations"]
            messages = next(
                (item["messages"] for item in found if item["id"] == conversation_id), []
            )
            if any(item["role"] == "assistant" for item in messages):
                break
            time.sleep(0.1)

        assert [item["content"] for item in messages if item["role"] == "assistant"] == [
            "thinking done"
        ]

        # And the run is still reattachable by conversation, with its whole log.
        # The reply is written just before the run marks itself done, so settle.
        deadline = time.monotonic() + 10
        snapshot = {}
        while time.monotonic() < deadline:
            listing.request("GET", f"/api/runs?conversation_id={conversation_id}&token={token}")
            snapshot = json.loads(listing.getresponse().read())["run"]
            if snapshot["state"] != "running":
                break
            time.sleep(0.1)
        assert snapshot["id"] == run_id
        assert snapshot["state"] == "succeeded"

        listing.request("GET", f"/api/runs/events?id={run_id}&after=0&token={token}")
        replay = [json.loads(line) for line in listing.getresponse().read().splitlines() if line]
        assert "".join(e["content"] for e in replay if e["type"] == "chunk") == "thinking done"
    finally:
        server.shutdown()
        server.server_close()


def test_a_running_turn_can_be_cancelled_over_http(tmp_path: Path, monkeypatch) -> None:
    """Stop used to abort only the socket, leaving the turn spending tokens."""
    import threading
    import time

    from magent import ui as ui_module

    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-cancel-test")
    started = threading.Event()

    class Endless:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, _conversation, _prompt, *, on_chunk=None, should_continue=None):
            started.set()
            if on_chunk:
                on_chunk("MagAgent", "partial answer")
            for _ in range(3000):
                if should_continue:
                    should_continue()
                time.sleep(0.01)
            return [{"content": "never", "speaker": "MagAgent"}]

    import magent.web_chat as web_chat

    monkeypatch.setattr(web_chat, "WebChatRunner", Endless)

    result = ui_module.serve_ui(
        store, project=tmp_path, username="ui-run-test", port=0, open_browser=False
    )
    if not result["ok"] and "Operation not permitted" in result.get("error", ""):
        pytest.skip("local socket binding is disabled by the test sandbox")
    server = result["server"]
    port = server.server_address[1]
    token = result["token"]
    write_headers = {"Content-Type": "application/json", "X-Magent-CSRF": token}

    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            f"/api/conversations?token={token}",
            body='{"kind":"chat","title":"Cancel"}',
            headers=write_headers,
        )
        conversation_id = json.loads(connection.getresponse().read())["conversation"]["id"]

        talker = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        talker.request(
            "POST",
            f"/api/conversations/message?token={token}",
            body=json.dumps({"conversation_id": conversation_id, "content": "go"}),
            headers=write_headers,
        )
        stream = talker.getresponse()
        run_id = json.loads(stream.fp.readline())["id"]
        assert started.wait(10)

        canceller = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        canceller.request(
            "POST",
            f"/api/runs/cancel?token={token}",
            body=json.dumps({"id": run_id}),
            headers=write_headers,
        )
        assert json.loads(canceller.getresponse().read())["ok"] is True

        # The stream must end promptly, not wait out the turn.
        asked = time.monotonic()
        tail = [json.loads(line) for line in stream.read().splitlines() if line]
        assert time.monotonic() - asked < 15
        assert tail[-1]["state"] == "cancelled"
        talker.close()

        # A cancelled turn leaves a trace, or the transcript shows a question
        # with no visible outcome.
        canceller.request("GET", f"/api/conversations?token={token}")
        found = json.loads(canceller.getresponse().read())["conversations"]
        messages = next(item["messages"] for item in found if item["id"] == conversation_id)
        cancelled = [item for item in messages if item.get("status") == "cancelled"]
        assert cancelled
        # Whatever was already said is kept. Watching text appear and then
        # vanish makes cancelling look like it erased the answer.
        assert "partial answer" in cancelled[0]["content"]
        assert "cancelled" in cancelled[0]["content"]
    finally:
        server.shutdown()
        server.server_close()


def test_a_tool_approval_can_be_answered_from_the_browser(tmp_path: Path, monkeypatch) -> None:
    """The Web UI ran with permissions non-interactive.

    Every tool above the auto-approve threshold was refused outright, so the
    agent could not do real work and never said why. The decision now travels
    the run's event log and comes back over HTTP.
    """
    import time

    from magent import ui as ui_module

    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("ui-approval-test")
    decided: dict[str, bool] = {}

    class NeedsPermission:
        def __init__(self, *_args, on_approval=None, **_kwargs) -> None:
            self.on_approval = on_approval

        def run(self, _conversation, _prompt, *, on_chunk=None, should_continue=None):
            allowed = self.on_approval("run `rm -rf build`", 2)
            decided["allowed"] = allowed
            return [{"content": f"allowed={allowed}", "speaker": "MagAgent"}]

    import magent.web_chat as web_chat

    monkeypatch.setattr(web_chat, "WebChatRunner", NeedsPermission)

    result = ui_module.serve_ui(
        store, project=tmp_path, username="ui-approval-test", port=0, open_browser=False
    )
    if not result["ok"] and "Operation not permitted" in result.get("error", ""):
        pytest.skip("local socket binding is disabled by the test sandbox")
    server = result["server"]
    port = server.server_address[1]
    token = result["token"]
    write_headers = {"Content-Type": "application/json", "X-Magent-CSRF": token}

    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            f"/api/conversations?token={token}",
            body='{"kind":"chat","title":"Approval"}',
            headers=write_headers,
        )
        conversation_id = json.loads(connection.getresponse().read())["conversation"]["id"]

        talker = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        talker.request(
            "POST",
            f"/api/conversations/message?token={token}",
            body=json.dumps({"conversation_id": conversation_id, "content": "clean up"}),
            headers=write_headers,
        )
        stream = talker.getresponse()
        run_id = json.loads(stream.fp.readline())["id"]

        # The prompt must reach the browser, and the turn must wait for it.
        asking = json.loads(stream.fp.readline())
        assert asking["type"] == "approval.requested"
        assert asking["description"] == "run `rm -rf build`"
        assert "allowed" not in decided

        answerer = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        answerer.request(
            "POST",
            f"/api/runs/approve?token={token}",
            body=json.dumps(
                {"id": run_id, "request_id": asking["request_id"], "approved": True}
            ),
            headers=write_headers,
        )
        assert json.loads(answerer.getresponse().read())["ok"] is True

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and "allowed" not in decided:
            time.sleep(0.05)
        assert decided["allowed"] is True

        # Answering the same request twice is a race, not a fault.
        answerer.request(
            "POST",
            f"/api/runs/approve?token={token}",
            body=json.dumps(
                {"id": run_id, "request_id": asking["request_id"], "approved": True}
            ),
            headers=write_headers,
        )
        stale = json.loads(answerer.getresponse().read())
        assert stale["ok"] is False
        assert "no longer waiting" in stale["error"]
        talker.close()
    finally:
        server.shutdown()
        server.server_close()


def test_an_unanswered_approval_denies_rather_than_hanging(tmp_path: Path, monkeypatch) -> None:
    """A tab that closed must not leave a tool authorised, or a thread parked."""
    import time

    from magent import ui as ui_module
    from magent import web_runs

    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(web_runs, "APPROVAL_TIMEOUT_SECONDS", 0.5)
    store = WorkbenchStore("ui-timeout-test")
    decided: dict[str, bool] = {}

    class NeedsPermission:
        def __init__(self, *_args, on_approval=None, **_kwargs) -> None:
            self.on_approval = on_approval

        def run(self, _conversation, _prompt, *, on_chunk=None, should_continue=None):
            decided["allowed"] = self.on_approval("do something risky", 2)
            return [{"content": "done", "speaker": "MagAgent"}]

    import magent.web_chat as web_chat

    monkeypatch.setattr(web_chat, "WebChatRunner", NeedsPermission)

    result = ui_module.serve_ui(
        store, project=tmp_path, username="ui-timeout-test", port=0, open_browser=False
    )
    if not result["ok"] and "Operation not permitted" in result.get("error", ""):
        pytest.skip("local socket binding is disabled by the test sandbox")
    server = result["server"]
    port = server.server_address[1]
    token = result["token"]
    write_headers = {"Content-Type": "application/json", "X-Magent-CSRF": token}

    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            f"/api/conversations?token={token}",
            body='{"kind":"chat","title":"Timeout"}',
            headers=write_headers,
        )
        conversation_id = json.loads(connection.getresponse().read())["conversation"]["id"]

        talker = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        talker.request(
            "POST",
            f"/api/conversations/message?token={token}",
            body=json.dumps({"conversation_id": conversation_id, "content": "go"}),
            headers=write_headers,
        )
        talker.getresponse()
        talker.close()  # nobody is watching, and nobody answers

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and "allowed" not in decided:
            time.sleep(0.05)
        assert decided["allowed"] is False
    finally:
        server.shutdown()
        server.server_close()
