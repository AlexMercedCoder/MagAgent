"""Durable turns for the Web UI.

A turn used to run on the HTTP request thread that started it, so closing the
tab mid-reply killed the work: the answer was never recorded, and there was no
way to stop a turn that was going nowhere.
"""

from __future__ import annotations

import threading
import time

import pytest

from magent.web_runs import (
    MAX_RETAINED_RUNS,
    TERMINAL_STATES,
    RunCancelled,
    RunStore,
)


def _settle(run, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if run.state in TERMINAL_STATES:
            return run.state
        time.sleep(0.01)
    raise AssertionError(f"run never finished; state={run.state}")


# --- lifecycle ---------------------------------------------------------------


def test_a_run_records_its_events_and_succeeds() -> None:
    store = RunStore()
    run = store.start("conv-1", lambda handle: handle.append({"type": "chunk", "content": "hi"}))

    assert _settle(run) == "succeeded"
    assert run.since(0) == [{"type": "chunk", "content": "hi"}]


def test_start_returns_before_the_work_finishes() -> None:
    """The whole point: the request thread must not wait on the turn."""
    release = threading.Event()
    store = RunStore()

    started = time.monotonic()
    run = store.start("conv-1", lambda _handle: release.wait(5))
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert run.state == "running"
    release.set()
    assert _settle(run) == "succeeded"


def test_a_run_finishes_even_with_nobody_reading() -> None:
    """Closing the tab used to kill the turn along with the socket."""
    done = threading.Event()
    store = RunStore()
    run = store.start("conv-1", lambda handle: (handle.append({"type": "done"}), done.set()))

    assert done.wait(5)
    assert _settle(run) == "succeeded"


def test_a_failing_run_reports_a_named_error() -> None:
    def explode(_handle):
        raise ConnectionError("provider unreachable")

    store = RunStore()
    run = store.start("conv-1", explode)

    assert _settle(run) == "failed"
    events = run.since(0)
    assert events[-1]["type"] == "error"
    # A raw repr tells the user nothing they can act on.
    assert events[-1].get("error")
    assert run.error


# --- cancellation ------------------------------------------------------------


def test_cancelling_stops_a_run_that_checks() -> None:
    started = threading.Event()

    def work(handle):
        started.set()
        for _ in range(500):
            handle.raise_if_cancelled()
            time.sleep(0.01)
        handle.append({"type": "done"})

    store = RunStore()
    run = store.start("conv-1", work)
    assert started.wait(5)

    assert store.cancel(run.id)["ok"] is True
    assert _settle(run) == "cancelled"
    assert run.since(0)[-1] == {"type": "cancelled"}


def test_cancelling_is_prompt() -> None:
    """A cancel that waits out the turn is no better than no cancel at all."""
    started = threading.Event()

    def work(handle):
        started.set()
        for _ in range(6000):  # a minute of work if never interrupted
            handle.raise_if_cancelled()
            time.sleep(0.01)

    store = RunStore()
    run = store.start("conv-1", work)
    assert started.wait(5)

    asked = time.monotonic()
    store.cancel(run.id)
    _settle(run, timeout=15)
    assert time.monotonic() - asked < 10


def test_cancelling_an_unknown_run_is_refused_by_name() -> None:
    result = RunStore().cancel("run_nonesuch")
    assert result["ok"] is False
    assert "run_nonesuch" in result["error"]


def test_cancelling_a_finished_run_is_not_an_error() -> None:
    """Saying it already finished is more useful than an error nobody can act on."""
    store = RunStore()
    run = store.start("conv-1", lambda _handle: None)
    _settle(run)

    result = store.cancel(run.id)
    assert result["ok"] is True
    assert result["state"] == "succeeded"
    assert "already finished" in result["note"]


def test_raise_if_cancelled_raises_only_after_a_cancel() -> None:
    store = RunStore()
    run = store.start("conv-1", lambda _handle: None)
    _settle(run)

    run.raise_if_cancelled()
    run.cancel()
    with pytest.raises(RunCancelled):
        run.raise_if_cancelled()


# --- cursors and reattachment ------------------------------------------------


def test_events_are_read_from_a_cursor() -> None:
    """Reattachment replays what a disconnected browser missed."""
    store = RunStore()
    gate = threading.Event()

    def work(handle):
        for index in range(3):
            handle.append({"type": "chunk", "content": str(index)})
        gate.set()

    run = store.start("conv-1", work)
    assert gate.wait(5)
    _settle(run)

    assert [event["content"] for event in run.since(0)] == ["0", "1", "2"]
    assert [event["content"] for event in run.since(2)] == ["2"]
    assert run.since(3) == []
    # Past the end is empty, not an error: a client can be ahead after a race.
    assert run.since(99) == []


def test_a_negative_cursor_reads_from_the_start() -> None:
    store = RunStore()
    run = store.start("conv-1", lambda handle: handle.append({"type": "chunk"}))
    _settle(run)
    assert len(run.since(-5)) == 1


def test_waiting_returns_as_soon_as_an_event_lands() -> None:
    """A reader blocks on the run instead of polling, so chunks arrive promptly."""
    store = RunStore()
    release = threading.Event()

    def work(handle):
        release.wait(5)
        handle.append({"type": "chunk", "content": "late"})

    run = store.start("conv-1", work)
    threading.Timer(0.2, release.set).start()

    started = time.monotonic()
    run.wait(0, timeout=10)
    assert time.monotonic() - started < 5
    _settle(run)


def test_waiting_returns_immediately_when_the_run_has_ended() -> None:
    """Otherwise a reader hangs for the full timeout after the last event."""
    store = RunStore()
    run = store.start("conv-1", lambda _handle: None)
    _settle(run)

    started = time.monotonic()
    run.wait(0, timeout=10)
    assert time.monotonic() - started < 1


def test_the_active_run_is_found_by_conversation() -> None:
    """A reloading tab knows its conversation, not the run id it lost."""
    store = RunStore()
    first = store.start("conv-1", lambda _h: None)
    _settle(first)
    time.sleep(0.01)
    second = store.start("conv-1", lambda _h: None)
    _settle(second)
    other = store.start("conv-2", lambda _h: None)
    _settle(other)

    assert store.active_for("conv-1").id == second.id
    assert store.active_for("conv-2").id == other.id
    assert store.active_for("conv-missing") is None


def test_a_snapshot_carries_what_a_client_needs_to_reattach() -> None:
    store = RunStore()
    run = store.start("conv-1", lambda handle: handle.append({"type": "chunk"}))
    _settle(run)

    snapshot = run.snapshot()
    assert snapshot["id"] == run.id
    assert snapshot["conversation_id"] == "conv-1"
    assert snapshot["state"] == "succeeded"
    assert snapshot["cursor"] == 1


# --- retention ---------------------------------------------------------------


def test_finished_runs_are_evicted_once_the_cap_is_passed() -> None:
    """Runs are held for reattachment, not as history; the store must not grow."""
    store = RunStore()
    runs = []
    for index in range(MAX_RETAINED_RUNS + 10):
        run = store.start(f"conv-{index}", lambda _h: None)
        _settle(run)
        runs.append(run)

    assert len(store._runs) <= MAX_RETAINED_RUNS
    # The newest are the ones a browser might still come back for.
    assert store.get(runs[-1].id) is not None
    assert store.get(runs[0].id) is None


def test_a_running_turn_is_never_evicted() -> None:
    """However old it is, it still has a reader coming."""
    release = threading.Event()
    store = RunStore()
    long_lived = store.start("conv-long", lambda _h: release.wait(20))

    for index in range(MAX_RETAINED_RUNS + 10):
        _settle(store.start(f"conv-{index}", lambda _h: None))

    assert store.get(long_lived.id) is not None
    release.set()
    _settle(long_lived)
