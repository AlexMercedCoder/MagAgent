"""A-3: the approval authority across real, separate processes (F01/F02)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from aais import ConflictError

from magent.approval_broker import ApprovalBroker
from magent.workbench_store import WorkbenchStore

ROOT = Path(__file__).resolve().parents[2]

CHILD = r"""
import json, sys
from pathlib import Path
from magent.approval_broker import ApprovalBroker
from magent.workbench_store import WorkbenchStore

root, session, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
store = WorkbenchStore.__new__(WorkbenchStore)
store.username, store.root, store.warnings = "test", root, []
broker = ApprovalBroker(store, project=root, grant_ttl_days=30)
action = {"kind": "tool.call", "name": "shell.exec", "summary": "Run: node --check app.js",
          "arguments": {"command": "node --check app.js"}}
if mode == "request":
    print(broker.request(action, origin={"session_id": session}, risk_level="medium",
                         risk_reasons=["test"], publish=lambda e: print(json.dumps({"published": e["type"]}), flush=True),
                         timeout=60, allow_session=True, allow_persistent=True), flush=True)
elif mode == "add":
    for _ in range(int(sys.argv[4])):
        broker.file.add_request(action=action, origin={"harness": "magagent", "session_id": session},
                                risk={"level": "low", "reasons": ["x"]},
                                choices=[{"decision": "approve", "scope": "once", "label": "ok"},
                                         {"decision": "deny", "scope": "once", "label": "no"}])
"""


def _store(root: Path) -> WorkbenchStore:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "test"
    store.root = root
    store.warnings = []
    return store


def _spawn(root: Path, *args: str) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.Popen(
        [sys.executable, "-c", CHILD, str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _pending(broker: ApprovalBroker, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = broker.snapshot()["snapshot"]["pending"]
        if pending:
            return pending[0]
        time.sleep(0.05)
    raise AssertionError("no pending request appeared")


HUMAN = {"id": "tester", "type": "human", "authenticated_by": "test"}


def test_decision_in_one_process_releases_the_waiting_process(tmp_path: Path) -> None:
    child = _spawn(tmp_path, "s1", "request")
    try:
        presenter = ApprovalBroker(_store(tmp_path), project=tmp_path, grant_ttl_days=30)
        request = _pending(presenter)
        presenter.decide(request["id"], decision="approve", scope="persistent", actor=HUMAN)
        out, err = child.communicate(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
    assert child.returncode == 0, err
    assert out.strip().splitlines()[-1] == "persistent"
    # The grant written by the presenter process is honoured by a new process.
    again = _spawn(tmp_path, "s2", "request")
    out, err = again.communicate(timeout=60)
    assert again.returncode == 0, err
    assert out.strip() == "persistent", "a remembered grant must not prompt"
    assert presenter.list_grants()[0]["hits"] == 1
    assert presenter.grant_hits()[-1]["session_id"] == "s2"


def test_killed_owner_is_orphaned_and_cannot_be_approved(tmp_path: Path) -> None:
    child = _spawn(tmp_path, "s1", "request")
    presenter = ApprovalBroker(_store(tmp_path), project=tmp_path)
    try:
        request = _pending(presenter)
    finally:
        child.kill()
        child.communicate()
    assert presenter.recovery()["orphaned"] == [request["id"]]
    with pytest.raises(ConflictError, match="issuing process stopped"):
        presenter.decide(request["id"], decision="approve", scope="once", actor=HUMAN)
    [receipt] = presenter.cancel_orphaned()
    assert receipt["resolution"]["outcome"] in {"cancelled", "denied"}
    assert presenter.recovery()["orphaned"] == []


def test_concurrent_writers_never_reuse_a_sequence(tmp_path: Path) -> None:
    children = [_spawn(tmp_path, f"s{index}", "add", "5") for index in range(4)]
    for child in children:
        _out, err = child.communicate(timeout=120)
        assert child.returncode == 0, err
    state = json.loads((tmp_path / "aais-approvals.json").read_text())
    sequences = [event["sequence"] for event in state["events"]]
    assert len(sequences) == 20
    assert sorted(sequences) == list(range(1, 21))
    assert len(state["pending"]) == 20
