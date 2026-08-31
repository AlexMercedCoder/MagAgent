from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from aais import ConflictError, action_digest, validate

from magent.approval_broker import ApprovalBroker
from magent.workbench_store import WorkbenchStore


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
