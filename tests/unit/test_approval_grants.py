"""G-1: approval grant lifecycle (expiry, revoke, receipts on grant hits)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aais import validate

from magent.approval_broker import ApprovalBroker, grant_id_for, grant_status
from magent.workbench_store import WorkbenchStore

ACTION = {
    "kind": "tool.call",
    "name": "shell.exec",
    "summary": "Run: node --check app.js",
    "arguments": {"command": "node --check app.js"},
}


def make_broker(tmp_path: Path, *, ttl: int = 30) -> ApprovalBroker:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "test"
    store.root = tmp_path
    store.warnings = []
    return ApprovalBroker(store, project=tmp_path, grant_ttl_days=ttl)


def _request(broker: ApprovalBroker, session: str, publish=None, timeout: float = 20) -> str:
    return broker.request(
        ACTION,
        origin={"session_id": session},
        risk_level="medium",
        risk_reasons=["test"],
        publish=publish or (lambda _event: None),
        timeout=timeout,
        allow_session=True,
        allow_persistent=True,
    )


def _wait_pending(broker: ApprovalBroker) -> dict:
    for _ in range(1000):
        pending = broker.snapshot()["snapshot"]["pending"]
        if pending:
            return pending[0]
        time.sleep(0.01)
    raise AssertionError("approval request was not published")


def grant(broker: ApprovalBroker, scope: str, session: str = "s1") -> None:
    result: list[str] = []
    thread = threading.Thread(target=lambda: result.append(_request(broker, session)))
    thread.start()
    request = _wait_pending(broker)
    broker.decide(
        request["id"],
        decision="approve",
        scope=scope,
        actor={"id": "tester", "type": "human", "authenticated_by": "test"},
    )
    thread.join(20)
    assert result == [scope]


def _state(broker: ApprovalBroker) -> dict:
    import json

    return json.loads(broker.path.read_text())


def _flat(broker: ApprovalBroker) -> dict:
    """Store state with MagAgent's extensions lifted to the top level."""

    state = _state(broker)
    return {**state, **state.get("extensions", {})}


def _set_grants(broker: ApprovalBroker, grants: list) -> None:
    with broker.transaction() as tx:
        tx.set_extension("grants", grants)


def test_new_persistent_grant_expires_after_default_ttl(tmp_path: Path) -> None:
    broker = make_broker(tmp_path, ttl=30)
    grant(broker, "persistent")
    [row] = broker.list_grants()
    assert row["id"].startswith("grt_") and not row["legacy"]
    assert row["status"] == "active"
    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    assert expires - created == timedelta(days=30)
    assert row["action_summary"] == ACTION["summary"]


def test_expired_persistent_grant_asks_again(tmp_path: Path) -> None:
    broker = make_broker(tmp_path)
    grant(broker, "persistent")
    grants = _flat(broker)["grants"]
    grants[0]["expires_at"] = "2000-01-01T00:00:00Z"
    _set_grants(broker, grants)
    assert broker.list_grants()[0]["status"] == "expired"

    published: list[dict] = []
    assert _request(broker, "s1", publish=published.append, timeout=0.3) == "deny"
    assert published and published[0]["type"] == "approval.requested"


def test_zero_ttl_disables_expiry(tmp_path: Path) -> None:
    broker = make_broker(tmp_path, ttl=0)
    grant(broker, "persistent")
    assert broker.list_grants()[0]["expires_at"] is None


def test_session_grants_do_not_get_a_calendar_expiry(tmp_path: Path) -> None:
    broker = make_broker(tmp_path)
    grant(broker, "session")
    assert broker.list_grants()[0]["expires_at"] is None


def test_grant_hit_writes_receipt_and_events(tmp_path: Path) -> None:
    broker = make_broker(tmp_path)
    grant(broker, "persistent")
    before = _flat(broker)
    sequence = int(before["sequence"])

    assert _request(broker, "another-session", publish=lambda _e: pytest.fail("no prompt")) == (
        "persistent"
    )

    state = _flat(broker)
    [hit] = state["grant_hits"]
    grant_id = state["grants"][0]["id"]
    assert hit["grant_id"] == grant_id
    assert hit["session_id"] == "another-session"
    resolution = state["resolutions"][hit["request_id"]]
    validate(resolution)
    assert resolution["resolution"]["outcome"] == "approved"
    assert resolution["resolution"]["effective_scope"] == "persistent"
    decision = state["decisions"][hit["request_id"]]
    assert decision["decision"]["actor"]["id"] == f"magent.grant:{grant_id}"
    assert decision["decision"]["actor"]["type"] == "policy"
    new_events = broker.events_after(sequence)
    assert [event["type"] for event in new_events] == ["approval.requested", "approval.resolved"]
    assert new_events[0]["request"]["choices"][0]["label"] == "Approved by a remembered grant"
    row = broker.list_grants()[0]
    assert row["hits"] == 1 and row["last_used_at"]
    assert broker.recovery()["receipts"][-1] == resolution
    assert broker.grant_hits()[-1] == hit


def test_revoke_by_id_makes_the_action_ask_again(tmp_path: Path) -> None:
    broker = make_broker(tmp_path)
    grant(broker, "persistent")
    grant_id = broker.list_grants()[0]["id"]

    result = broker.revoke_grants([grant_id], actor="alex")
    assert result == {"ok": True, "revoked": [grant_id], "missing": []}
    row = broker.list_grants()[0]
    assert row["status"] == "revoked" and row["revoked_by"] == "alex"
    assert broker.list_grants(include_inactive=False) == []

    published: list[dict] = []
    assert _request(broker, "s1", publish=published.append, timeout=0.3) == "deny"
    assert published


def test_revoke_unknown_id_reports_missing(tmp_path: Path) -> None:
    broker = make_broker(tmp_path)
    assert broker.revoke_grants(["grt_nope"]) == {
        "ok": False,
        "revoked": [],
        "missing": ["grt_nope"],
    }


def test_revoke_expired_and_all(tmp_path: Path) -> None:
    broker = make_broker(tmp_path)
    grant(broker, "session", session="s2")
    grant(broker, "persistent")
    grants = _flat(broker)["grants"]
    grants[1]["expires_at"] = "2000-01-01T00:00:00Z"
    _set_grants(broker, grants)

    expired = broker.revoke_grants(expired=True)
    assert len(expired["revoked"]) == 1
    everything = broker.revoke_grants(all_grants=True)
    assert len(everything["revoked"]) == 1
    assert {row["status"] for row in broker.list_grants()} == {"revoked"}


def test_legacy_grants_are_grandfathered_and_flagged(tmp_path: Path) -> None:
    broker = make_broker(tmp_path)
    grant(broker, "persistent")
    state = _flat(broker)
    legacy = {
        key: state["grants"][0][key]
        for key in ("action_digest", "scope", "session_id", "created_at")
    }
    _set_grants(broker, [legacy])

    [row] = broker.list_grants()
    assert row["legacy"] is True
    assert row["status"] == "active"
    assert row["expires_at"] is None
    assert "never expires" in row["flag"]
    assert row["id"] == grant_id_for(legacy) and row["id"].startswith("grt_legacy_")
    # The action summary is recovered from the event log.
    assert row["action_summary"] == ACTION["summary"]
    # Still honoured (grandfathered), and the hit is still receipted.
    assert _request(broker, "s9", publish=lambda _e: pytest.fail("no prompt")) == "persistent"
    assert _flat(broker)["grant_hits"][-1]["grant_id"] == row["id"]
    # Revocable by its derived id.
    assert broker.revoke_grants([row["id"]])["revoked"] == [row["id"]]


def test_grant_status_helper() -> None:
    now = datetime(2026, 9, 27, tzinfo=UTC)
    assert grant_status({}, now) == "active"
    assert grant_status({"expires_at": "2026-09-26T00:00:00Z"}, now) == "expired"
    assert grant_status({"expires_at": "2026-10-26T00:00:00Z"}, now) == "active"
    assert grant_status({"revoked_at": "x"}, now) == "revoked"


def test_configured_ttl_is_read_from_config(tmp_path: Path, monkeypatch) -> None:
    import magent.approval_broker as module

    monkeypatch.setattr(module, "configured_grant_ttl_days", lambda _user=None: 7)
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "test"
    store.root = tmp_path
    store.warnings = []
    assert ApprovalBroker(store, project=tmp_path).grant_ttl_days == 7


def test_config_property_defaults_and_overrides() -> None:
    from magent.config import Config

    assert Config({}, {}).approval_grant_ttl_days == 30
    assert Config({"permissions": {"grant_ttl_days": 5}}, {}).approval_grant_ttl_days == 5
    assert (
        Config(
            {"permissions": {"grant_ttl_days": 5}}, {"permissions": {"grant_ttl_days": 0}}
        ).approval_grant_ttl_days
        == 0
    )
    assert Config({"permissions": {"grant_ttl_days": "bad"}}, {}).approval_grant_ttl_days == 30


def test_grants_cli_list_and_revoke(monkeypatch, tmp_path: Path) -> None:
    import json

    from typer.testing import CliRunner

    from magent.cli import main as cli_main
    from tests.unit.test_cli import redirect_config

    redirect_config(monkeypatch, tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "alex"]).exit_code == 0

    empty = runner.invoke(cli_main.app, ["permission", "grants", "list"])
    assert empty.exit_code == 0 and "No remembered approval grants" in empty.output

    store = WorkbenchStore("alex")
    broker = ApprovalBroker(store, project=tmp_path, grant_ttl_days=30)
    grant(broker, "persistent")
    grant_id = broker.list_grants()[0]["id"]

    listed = runner.invoke(cli_main.app, ["permission", "grants", "list", "--json"])
    assert listed.exit_code == 0
    payload = json.loads(listed.output)
    assert payload["schema"] == "magent.approval-grants.v1"
    assert payload["grant_ttl_days"] == 30
    assert payload["grants"][0]["id"] == grant_id

    table = runner.invoke(cli_main.app, ["permission", "grants", "list"])
    assert table.exit_code == 0 and grant_id in table.output

    usage = runner.invoke(cli_main.app, ["permission", "grants", "revoke"])
    assert usage.exit_code == 2 and "--expired" in usage.output
    needs_yes = runner.invoke(cli_main.app, ["permission", "grants", "revoke", "--all"])
    assert needs_yes.exit_code == 2

    unknown = runner.invoke(cli_main.app, ["permission", "grants", "revoke", "grt_missing"])
    assert unknown.exit_code == 1 and "Unknown grant id" in unknown.output

    revoked = runner.invoke(cli_main.app, ["permission", "grants", "revoke", grant_id, "--json"])
    assert revoked.exit_code == 0
    assert json.loads(revoked.output)["revoked"] == [grant_id]
    active = runner.invoke(cli_main.app, ["permission", "grants", "list", "--active", "--json"])
    assert json.loads(active.output)["grants"] == []
