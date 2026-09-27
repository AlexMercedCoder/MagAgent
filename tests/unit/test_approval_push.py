"""G-7: approval events are pushed (doorbells + in-process bus), not polled."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

import magent.approval_broker as broker_module
from magent.approval_broker import ApprovalBroker
from magent.approval_bus import ApprovalEventBus, Doorbell, ring_all, ring_one
from magent.workbench_store import WorkbenchStore

ACTION = {
    "kind": "tool.call",
    "name": "shell.exec",
    "summary": "Run: make test",
    "arguments": {"command": "make test"},
}
HUMAN = {"id": "tester", "type": "human", "authenticated_by": "test"}


def _store(root: Path) -> WorkbenchStore:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "test"
    store.root = root
    store.warnings = []
    return store


def test_doorbell_wakes_on_ring_and_times_out_otherwise() -> None:
    bell = Doorbell()
    try:
        assert bell.wait(0.05) is False
        assert ring_one(bell.record()) is True
        assert bell.wait(5) is True
    finally:
        bell.close()
    assert ring_all([bell.record()]) == [bell.id]  # closed: reported dead


def test_bus_wakes_readers_and_deduplicates() -> None:
    bus = ApprovalEventBus()
    woke: list[int] = []
    thread = threading.Thread(target=lambda: woke.append(bus.wait(0, 5)))
    thread.start()
    bus.publish({"stream": "s", "sequence": 1})
    bus.publish({"stream": "s", "sequence": 1})
    thread.join(5)
    assert woke == [1] and bus.version == 1


def test_a_decision_from_another_broker_is_pushed_not_polled(tmp_path: Path, monkeypatch) -> None:
    # With the safety poll pushed out to a minute, only a ring can wake the
    # waiter in time.
    monkeypatch.setattr(broker_module, "SAFETY_POLL_SECONDS", 60.0)
    waiter = ApprovalBroker(_store(tmp_path), project=tmp_path)
    presenter = ApprovalBroker(_store(tmp_path), project=tmp_path)
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            waiter.request(
                ACTION,
                origin={"session_id": "s1"},
                risk_level="medium",
                risk_reasons=["test"],
                publish=lambda _e: None,
                timeout=120,
            )
        )
    )
    thread.start()
    try:
        deadline = time.monotonic() + 60
        pending: list = []
        while not pending and time.monotonic() < deadline:
            pending = presenter.snapshot()["snapshot"]["pending"]
            time.sleep(0.05)
        assert pending
        doorbells = presenter.file.get_extension("doorbells", [])
        assert any(item["kind"] == "waiter" for item in doorbells)
        decided_at = time.monotonic()
        presenter.decide(pending[0]["id"], decision="approve", scope="once", actor=HUMAN)
        thread.join(40)
        assert result == ["once"]
        assert time.monotonic() - decided_at < 40
    finally:
        waiter.close()
        presenter.close()
    assert presenter.file.get_extension("doorbells", []) == []


def test_web_ui_pushes_the_pending_snapshot(tmp_path: Path, monkeypatch) -> None:
    from magent.ui import serve_ui
    from tests.unit.test_cli import redirect_config

    redirect_config(monkeypatch, tmp_path)
    store = WorkbenchStore("alex")
    result = serve_ui(store, project=tmp_path, username="alex", port=0)
    if not result.get("ok"):
        pytest.skip(result.get("error"))
    server = result["server"]
    try:
        port = server.server_address[1]
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/approvals/stream",
            headers={"X-Magent-Token": result["token"], "X-Magent-CSRF": result["token"]},
        )
        response = urllib.request.urlopen(request, timeout=60)
        first = json.loads(response.readline())
        assert first["type"] == "approvals" and first["snapshot"]["pending"] == []

        other = ApprovalBroker(WorkbenchStore("alex"), project=tmp_path)
        other.file.add_request(
            action=ACTION,
            origin={"harness": "magagent", "session_id": "cli"},
            risk={"level": "low", "reasons": ["x"]},
            choices=[
                {"decision": "approve", "scope": "once", "label": "ok"},
                {"decision": "deny", "scope": "once", "label": "no"},
            ],
        )
        other._ring()  # what a real write does after committing
        deadline = time.monotonic() + 30
        pushed = None
        while time.monotonic() < deadline:
            line = json.loads(response.readline())
            if line["type"] == "approvals" and line["snapshot"]["pending"]:
                pushed = line
                break
        assert pushed and pushed["snapshot"]["pending"][0]["action"]["summary"] == "Run: make test"
        response.close()
        other.close()
    finally:
        server.shutdown()
        server.server_close()
