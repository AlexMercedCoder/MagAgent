"""Regressions for the 1.4.1 follow-ups: criteria sandboxing and stored run records."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from magent.agraph.record import validate_run_record
from magent.agraph.status import graph_status, stored_run_record
from magent.cli.commands.graph import _find_run
from magent.desktop_api import graph_catalog
from magent.tools import executor as executor_module
from tests.unit.test_release_141 import _command_node, _executor, _graph

EXE = sys.executable


def test_command_criteria_run_in_the_configured_shell_sandbox(tmp_path: Path, monkeypatch) -> None:
    seen: list[tuple[str, bool]] = []
    original = executor_module.ToolExecutor.__init__

    def spy(self, *args, **kwargs):
        original(self, *args, **kwargs)
        seen.append((self.shell_sandbox, self.shell_sandbox_network))

    monkeypatch.setattr(executor_module.ToolExecutor, "__init__", spy)
    node = _command_node(tmp_path, f"{EXE} check.py", f"{EXE}*")
    graph_executor = _executor(
        tmp_path,
        permissions={
            "allowed_shell_patterns": [f"{EXE} *"],
            "shell_sandbox": "bubblewrap",
            "shell_sandbox_network": True,
        },
        assume_yes=True,
    )
    asyncio.run(graph_executor.run(_graph(node)))
    assert ("bubblewrap", True) in seen


def test_stored_run_record_is_a_valid_ags_run_record(tmp_path: Path) -> None:
    graph_executor = _executor(tmp_path)
    result = asyncio.run(graph_executor.run(_graph({})))
    [stored] = graph_executor.store.read("graph_runs", [])
    assert not {"id", "created_at", "updated_at"} & stored.keys()
    validate_run_record(stored)
    found = _find_run(graph_executor.store, result["run"]["run_id"])
    assert found is not None
    validate_run_record(found)


def test_legacy_store_keys_are_dropped_on_read(tmp_path: Path, monkeypatch) -> None:
    graph_executor = _executor(tmp_path)
    result = asyncio.run(graph_executor.run(_graph({})))
    store = graph_executor.store
    [stored] = store.read("graph_runs", [])
    legacy = {"id": "graph_run_0001", "created_at": "2026-11-05T00:00:00Z", **stored}
    store.write("graph_runs", [legacy])
    run_id = result["run"]["run_id"]

    validate_run_record(stored_run_record(legacy))
    found = _find_run(store, run_id)
    assert found is not None and "id" not in found
    assert graph_status(store, run_id) is not None

    monkeypatch.setattr("magent.workbench_store.WorkbenchStore", lambda _user: store)
    [listed] = graph_catalog("test")["runs"]
    validate_run_record(listed)
