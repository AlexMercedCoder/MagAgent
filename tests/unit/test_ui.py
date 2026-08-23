from __future__ import annotations

import http.client
from pathlib import Path

import pytest

import magent.ui as ui_module
from magent import workbench
from magent.ui import render_ui_html, serve_ui, ui_state
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


def test_render_ui_html_contains_local_endpoints() -> None:
    html = render_ui_html()

    assert "MagAgent" in html
    assert "New chat" in html
    assert "Group conversation" in html
    assert "Graph Kanban" in html
    assert "Blank graph" in html
    assert "Generate with AI" in html
    assert "Add card" in html
    assert "Profiles" in html
    assert "Settings" in html
    assert "Operations" in html
    assert "/assets/app.js" in html


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

        connection.request("GET", f"/api/conversations?token={token}")
        assert connection.getresponse().status == 405

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
