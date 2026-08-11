from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from magent.task_runtime import (
    EVENT_SCHEMA_VERSION,
    TASK_SCHEMA_VERSION,
    TaskRuntime,
    TaskRuntimeError,
    _load_json,
)


def test_task_lifecycle_is_durable_and_versioned(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)
    task = runtime.create(
        "ask",
        "Fix the tests",
        project=tmp_path,
        session_id="session-1",
        planning_role="review",
        execution_role="coding",
        permission_policy="balanced",
    )

    running = runtime.transition(task["id"], "running")
    runtime.record_event(task["id"], "tool_started", detail={"tool": "read_file"})
    updated = runtime.update_context(
        task["id"],
        usage={"total_tokens": 42, "cost_usd": 0.001},
        files_changed=["app.py", "app.py"],
        checkpoints=["checkpoint_1"],
        final_audit={"tests": "passed"},
    )
    completed = runtime.transition(task["id"], "validating")
    completed = runtime.transition(task["id"], "completed")

    reopened = TaskRuntime(tmp_path)
    stored = reopened.get(task["id"])
    events = reopened.events(task["id"])

    assert task["schema_version"] == TASK_SCHEMA_VERSION
    assert running["started_at"]
    assert updated["files_changed"] == ["app.py"]
    assert completed["state"] == "completed"
    assert completed["finished_at"]
    assert stored and stored["usage"]["total_tokens"] == 42
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["schema_version"] == EVENT_SCHEMA_VERSION for event in events)
    assert events[-1]["type"] == "state_changed"


def test_task_transitions_reject_invalid_state_changes_and_support_retry(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)
    task = runtime.create("recipe", "Release prep", project=tmp_path)

    with pytest.raises(TaskRuntimeError, match="queued -> completed"):
        runtime.transition(task["id"], "completed")

    runtime.transition(task["id"], "running")
    runtime.transition(task["id"], "failed", reason="tests failed")
    retried = runtime.retry(task["id"])

    assert retried["state"] == "queued"
    assert retried["attempt"] == 2
    assert retried["finished_at"] == ""


def test_parent_child_filters_and_event_cursor(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)
    parent = runtime.create("goal", "Ship feature", project=tmp_path)
    child = runtime.create(
        "goal_step",
        "Implement",
        project=tmp_path,
        parent_task_id=parent["id"],
    )
    runtime.record_event(child["id"], "progress", detail={"percent": 50})

    children = runtime.list_tasks(parent_task_id=parent["id"])
    later = runtime.events(child["id"], after=1)

    assert [item["id"] for item in children] == [child["id"]]
    assert [event["type"] for event in later] == ["progress"]


def test_concurrent_event_writers_keep_a_single_ordered_stream(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)
    task = runtime.create("ask", "Concurrent work", project=tmp_path)

    def write_event(index: int) -> None:
        TaskRuntime(tmp_path).record_event(task["id"], "progress", detail={"index": index})

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write_event, range(24)))

    events = runtime.events(task["id"])
    assert len(events) == 25
    assert [event["sequence"] for event in events] == list(range(1, 26))


def test_task_runtime_uses_wal_with_full_sync(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)

    connection = sqlite3.connect(runtime.path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()
    with runtime._connect() as connection:
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_task_runtime_appends_event_batches_atomically(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)
    task = runtime.create("ask", "Batch", project=tmp_path)

    appended = runtime.record_events(
        task["id"],
        [
            {"type": "progress", "detail": {"percent": 25}},
            {"type": "progress", "detail": {"percent": 50}},
        ],
    )

    assert [event["sequence"] for event in appended] == [2, 3]
    assert [event["detail"]["percent"] for event in appended] == [25, 50]
    assert [event["sequence"] for event in runtime.events(task["id"])] == [1, 2, 3]


def test_task_runtime_rejects_unknown_and_missing_records(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)

    with pytest.raises(TaskRuntimeError, match="Unknown task state"):
        runtime.create("ask", "Bad", project=tmp_path, state="unknown")  # type: ignore[arg-type]
    with pytest.raises(TaskRuntimeError, match="Task not found"):
        runtime.record_event("missing", "progress")
    with pytest.raises(TaskRuntimeError, match="Unknown task state"):
        runtime.transition("missing", "unknown")  # type: ignore[arg-type]
    with pytest.raises(TaskRuntimeError, match="Task not found"):
        runtime.transition("missing", "running")
    with pytest.raises(TaskRuntimeError, match="Task not found"):
        runtime.update_context("missing", usage={"tokens": 1})

    assert runtime.record_events("missing", []) == []
    with pytest.raises(TaskRuntimeError, match="1000-event limit"):
        runtime.record_events("missing", [{"type": "progress"}] * 1001)


def test_task_runtime_filters_noops_and_controls(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)
    parent = runtime.create("goal", "Parent", project=tmp_path, project_id="project-one")
    child = runtime.create(
        "step",
        "Child",
        project=tmp_path,
        project_id="project-one",
        parent_task_id=parent["id"],
    )
    runtime.create("other", "Other", project=tmp_path, project_id="project-two")

    assert runtime.transition(parent["id"], "queued")["state"] == "queued"
    assert [item["id"] for item in runtime.list_tasks(project_id="project-one", limit=1)] == [
        child["id"]
    ]
    assert [item["id"] for item in runtime.list_tasks(state="queued", parent_task_id=parent["id"])] == [
        child["id"]
    ]

    runtime.transition(child["id"], "running")
    assert runtime.pause(child["id"])["state"] == "waiting"
    assert runtime.resume(child["id"])["state"] == "running"
    assert runtime.cancel(child["id"])["state"] == "cancelled"


def test_task_runtime_json_fallback_handles_corrupt_values() -> None:
    assert _load_json("not-json", {"safe": True}) == {"safe": True}
    assert _load_json(None, []) == []  # type: ignore[arg-type]
