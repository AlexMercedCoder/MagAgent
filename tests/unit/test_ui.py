from __future__ import annotations

from pathlib import Path

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
    assert any(topic["slug"] == "ui" for topic in state["docs"])


def test_render_ui_html_contains_local_endpoints() -> None:
    html = render_ui_html()

    assert "MagAgent UI" in html
    assert "/api/state" in html
    assert "/api/docs/search" in html
    assert "/api/release/check" in html


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
    assert result["url"] == "http://127.0.0.1:7831/"
    assert result["project"] == str(tmp_path.resolve())
    assert started["ok"] is True
