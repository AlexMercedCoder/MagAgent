from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from magent.execution_bridge import SessionTaskBridge
from magent.workbench_store import WorkbenchStore


class FakeLogger:
    def __init__(self) -> None:
        self.callback = None

    def set_event_callback(self, callback) -> None:
        self.callback = callback


class FakeSession:
    session_id = "session-bridge"
    turn_count = 2

    def __init__(self, project: Path) -> None:
        self.logger = FakeLogger()
        self.scratchpad = {
            "files_touched": [str(project / "app.py")],
            "commands_run": ["pytest -q"],
            "permission_failures": [],
        }


def test_bridge_forwards_live_events_and_completes_with_evidence(tmp_path: Path) -> None:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "alice"
    store.root = tmp_path / "workbench"
    store.root.mkdir(parents=True)
    session = FakeSession(tmp_path)
    bridge = SessionTaskBridge(
        store,
        session,
        kind="interactive_session",
        title="Interactive",
        project=str(tmp_path),
        permission_policy="balanced",
        provider=SimpleNamespace(provider_id="ollama", model="qwen"),
    )

    assert session.logger.callback is not None
    assert session.execution_task_id == bridge.task_id
    session.logger.callback(
        {"event": "activity_event", "session": session.session_id, "user": "alice", "tool": "read_file"}
    )
    completed = bridge.complete({"ok": True, "checks": ["pytest -q"]})
    events = bridge.runtime.events(bridge.task_id)

    assert completed["state"] == "completed"
    assert completed["files_changed"] == [str(tmp_path / "app.py")]
    assert completed["metadata"]["turns"] == 2
    assert any(event["type"] == "session.activity_event" for event in events)
    assert session.logger.callback is None


def test_bridge_failure_is_idempotent(tmp_path: Path) -> None:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "alice"
    store.root = tmp_path / "workbench"
    store.root.mkdir(parents=True)
    bridge = SessionTaskBridge(
        store,
        FakeSession(tmp_path),
        kind="ask",
        title="Fail",
        project=str(tmp_path),
        permission_policy="balanced",
        provider=SimpleNamespace(provider_id="test", model="test"),
    )

    failed = bridge.fail(RuntimeError("network down"))
    repeated = bridge.fail("ignored")

    assert failed["state"] == "failed"
    assert repeated["state"] == "failed"
    assert repeated["final_audit"]["error"] == "network down"
