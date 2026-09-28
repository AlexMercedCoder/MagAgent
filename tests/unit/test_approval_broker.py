from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from aais import ConflictError, action_digest, validate

from magent.approval_broker import ApprovalBroker
from magent.workbench_store import WorkbenchStore


def test_external_decision_wakes_original_broker(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor

    owner, presenter = broker(tmp_path), broker(tmp_path)
    with ThreadPoolExecutor() as pool:
        run = pool.submit(
            owner.request_legacy,
            "Run: node --check app.js",
            2,
            origin={"session_id": "session-1"},
            publish=lambda _: None,
            timeout=5,
        )
        request = wait_for_request(presenter)
        with pytest.raises(ConflictError):
            presenter.decide(
                request["id"],
                decision="approve",
                scope="once",
                actor={"id": "tester", "type": "human"},
                reviewed_digest="sha256:" + "0" * 64,
            )
        presenter.decide(
            request["id"], decision="approve", scope="once", actor={"id": "tester", "type": "human"}
        )
        assert run.result(timeout=3) == "once"


def test_corrupt_legacy_state_requires_recovery_and_is_left_untouched(tmp_path: Path):
    from magent.workbench_store import WorkbenchStoreError

    instance = broker(tmp_path)
    path = tmp_path / "aais_approvals.json"
    path.write_text('{"pending":')
    with pytest.raises(WorkbenchStoreError, match="recovery"):
        instance.snapshot()
    assert path.read_text() == '{"pending":'
    assert not (tmp_path / "aais-approvals.json").exists()


def test_corrupt_store_is_quarantined_and_requires_recovery(tmp_path: Path):
    from magent.workbench_store import WorkbenchStoreError

    instance = broker(tmp_path)
    path = tmp_path / "aais-approvals.json"
    path.write_text('{"pending":')
    with pytest.raises(WorkbenchStoreError, match="recovery"):
        instance.snapshot()
    assert list(tmp_path.glob("aais-approvals.json.corrupt-*"))
    # Still refused (from any process) until an operator acknowledges it.
    with pytest.raises(WorkbenchStoreError, match="recovery"):
        broker(tmp_path).snapshot()


def test_legacy_state_is_imported_once_with_grants(tmp_path: Path):
    import json

    legacy = {
        "schema": "magent.aais-store.v1",
        "sequence": 7,
        "presenter_sequence": 3,
        "pending": {},
        "resolutions": {},
        "decisions": {},
        "grants": [
            {
                "action_digest": "sha256:" + "a" * 64,
                "scope": "persistent",
                "session_id": "",
                "created_at": "2026-09-01T00:00:00Z",
            }
        ],
        "events": [],
        "owners": {},
    }
    (tmp_path / "aais_approvals.json").write_text(json.dumps(legacy))
    instance = broker(tmp_path)
    [row] = instance.list_grants()
    assert row["legacy"] is True and row["status"] == "active"
    assert not (tmp_path / "aais_approvals.json").exists()
    assert list(tmp_path.glob("aais_approvals.json.migrated-*"))
    with instance.transaction() as tx:
        assert tx.sequence == 7


def broker(tmp_path: Path) -> ApprovalBroker:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "test"
    store.root = tmp_path
    store.warnings = []
    return ApprovalBroker(store, project=tmp_path)


def wait_for_request(instance: ApprovalBroker) -> dict:
    for _ in range(1000):
        pending = instance.snapshot()["snapshot"]["pending"]
        if pending:
            return pending[0]
        time.sleep(0.01)
    raise AssertionError("approval request was not published")


def test_request_is_persisted_before_publish_and_resumes_after_exact_decision(tmp_path: Path):
    instance = broker(tmp_path)
    events: list[dict] = []
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            instance.request_legacy(
                "Run: node --check app.js",
                2,
                origin={"session_id": "session-1", "run_id": "run-1"},
                publish=events.append,
                timeout=20,
                allow_persistent=True,
            )
        )
    )
    thread.start()
    request = wait_for_request(instance)
    # The request is persisted (and so visible in the snapshot) before it is published, so the
    # publish can land a moment later on a loaded machine.
    deadline = time.monotonic() + 10
    while not events and time.monotonic() < deadline:
        time.sleep(0.01)
    assert events and events[0]["type"] == "approval.requested"
    assert request["action_digest"] == action_digest(request["action"])
    resolution = instance.decide(
        request["id"],
        decision="approve",
        scope="once",
        actor={"id": "tester", "type": "human", "authenticated_by": "test"},
        decision_id="dec_test_once",
    )
    thread.join(20)
    assert result == ["once"]
    assert resolution["resolution"]["outcome"] == "approved"
    assert instance.snapshot()["snapshot"]["pending"] == []
    assert all(validate(event) for event in events)


def test_duplicate_decision_is_idempotent_and_conflict_fails_closed(tmp_path: Path):
    instance = broker(tmp_path)
    thread = threading.Thread(
        target=lambda: instance.request_legacy(
            "Protected action",
            2,
            origin={"session_id": "session-1"},
            publish=lambda _event: None,
            timeout=20,
        )
    )
    thread.start()
    request = wait_for_request(instance)
    actor = {"id": "tester", "type": "human", "authenticated_by": "test"}
    first = instance.decide(
        request["id"], decision="deny", scope="once", actor=actor, decision_id="dec_test_deny"
    )
    assert (
        instance.decide(
            request["id"], decision="deny", scope="once", actor=actor, decision_id="dec_retry"
        )
        == first
    )
    with pytest.raises(ConflictError):
        instance.decide(request["id"], decision="approve", scope="once", actor=actor)
    thread.join(20)


def test_changed_action_is_resolved_stale(tmp_path: Path):
    instance = broker(tmp_path)
    current = {"value": "one"}
    action = {
        "kind": "tool.call",
        "name": "test.action",
        "summary": "Test exact action",
        "arguments": {"value": "one"},
    }
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            instance.request(
                action,
                origin={"session_id": "session-1"},
                risk_level="medium",
                risk_reasons=["test"],
                publish=lambda _event: None,
                timeout=20,
                current_action=lambda: {**action, "arguments": dict(current)},
            )
        )
    )
    thread.start()
    request = wait_for_request(instance)
    current["value"] = "two"
    resolution = instance.decide(
        request["id"],
        decision="approve",
        scope="once",
        actor={"id": "tester", "type": "human", "authenticated_by": "test"},
    )
    thread.join(20)
    assert resolution["resolution"]["outcome"] == "stale"
    assert result == ["deny"]


def test_owner_cancellation_resolves_waiting_request(tmp_path: Path):
    instance = broker(tmp_path)
    result: list[str] = []
    thread = threading.Thread(
        target=lambda: result.append(
            instance.request_legacy(
                "Protected action",
                2,
                origin={"session_id": "session-1", "run_id": "run-1"},
                publish=lambda _event: None,
                timeout=20,
            )
        )
    )
    thread.start()
    wait_for_request(instance)
    assert instance.cancel_owner(run_id="run-1") == 1
    thread.join(20)
    assert result == ["deny"]


def test_session_grant_is_exact_and_does_not_cross_sessions(tmp_path: Path):
    instance = broker(tmp_path)
    action = {
        "kind": "tool.call",
        "name": "shell.exec",
        "summary": "Check syntax",
        "arguments": {"command": "node --check app.js"},
    }
    first = threading.Thread(
        target=lambda: instance.request(
            action,
            origin={"session_id": "session-1"},
            risk_level="medium",
            risk_reasons=["test"],
            publish=lambda _event: None,
            timeout=20,
        )
    )
    first.start()
    request = wait_for_request(instance)
    instance.decide(
        request["id"],
        decision="approve",
        scope="session",
        actor={"id": "tester", "type": "human", "authenticated_by": "test"},
    )
    first.join(20)

    assert (
        instance.request(
            action,
            origin={"session_id": "session-1"},
            risk_level="medium",
            risk_reasons=["test"],
            publish=lambda _event: pytest.fail("same-session grant should be remembered"),
            timeout=1,
        )
        == "session"
    )

    other = threading.Thread(
        target=lambda: instance.request(
            action,
            origin={"session_id": "session-2"},
            risk_level="medium",
            risk_reasons=["test"],
            publish=lambda _event: None,
            timeout=20,
        )
    )
    other.start()
    request = wait_for_request(instance)
    instance.decide(
        request["id"],
        decision="deny",
        scope="once",
        actor={"id": "tester", "type": "human", "authenticated_by": "test"},
    )
    other.join(20)


def test_dead_owner_is_recovered_without_new_approval(tmp_path):
    import subprocess
    import sys

    from aais.liveness import OwnerIdentity, current_host_id, process_start_time

    instance = broker(tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        start = None
        for _ in range(100):
            start = process_start_time(child.pid)
            if start is not None:
                break
            time.sleep(0.02)
        owner = OwnerIdentity(child.pid, start, current_host_id())
    finally:
        child.kill()
        child.wait()
    envelope = instance.file.add_request(
        action={
            "kind": "tool.call",
            "name": "shell.exec",
            "summary": "Check syntax",
            "arguments": {},
        },
        origin={"harness": "magagent", "session_id": "fixture"},
        risk={"level": "low", "reasons": ["Protected action"]},
        choices=[
            {"decision": "approve", "scope": "once", "label": "Allow once"},
            {"decision": "deny", "scope": "once", "label": "Deny"},
        ],
        owner=owner,
    )
    key = envelope["request"]["id"]
    assert instance.recovery()["orphaned"] == [key]
    assert instance.snapshot()["snapshot"]["pending"] == []
    with pytest.raises(ConflictError, match="issuing process stopped"):
        instance.decide(
            key, decision="approve", scope="once", actor={"id": "test", "type": "human"}
        )
    denied = instance.decide(
        key, decision="deny", scope="once", actor={"id": "test", "type": "human"}
    )
    assert denied["resolution"]["outcome"] == "denied"


def test_approvals_recovery_command(monkeypatch, tmp_path: Path):
    import json

    from typer.testing import CliRunner

    from magent.cli import main as cli_main
    from tests.unit.test_cli import redirect_config

    redirect_config(monkeypatch, tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "alex"]).exit_code == 0
    healthy = runner.invoke(cli_main.app, ["permission", "approvals-recovery", "--json"])
    assert healthy.exit_code == 0, healthy.output
    assert json.loads(healthy.output)["report"]["orphaned"] == []

    state = WorkbenchStore("alex").root / "aais-approvals.json"
    state.write_text("{broken")
    broken = runner.invoke(cli_main.app, ["permission", "approvals-recovery"])
    assert broken.exit_code == 1
    assert "--acknowledge" in broken.output
    fixed = runner.invoke(cli_main.app, ["permission", "approvals-recovery", "--acknowledge"])
    assert fixed.exit_code == 0, fixed.output
    assert "Recovery acknowledged" in fixed.output
