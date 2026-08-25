from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from magent.daemon import enqueue_task, list_queue, run_once
from magent.task_runtime import TaskRuntime
from magent.workbench_store import WorkbenchStore


def _store(tmp_path: Path) -> WorkbenchStore:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "alice"
    store.root = tmp_path / "workbench"
    store.root.mkdir(parents=True)
    return store


# Far below the child's sleep, far above the write latency of a loaded machine.
CANCEL_BUDGET_SECONDS = 15
# Claiming the item and cold-starting a Python child is unrelated to
# cancellation, and on a loaded machine it can take well over ten seconds.
STARTUP_GRACE_SECONDS = 60


def test_running_daemon_process_observes_durable_cancellation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queued = enqueue_task(
        store,
        "shell",
        {"command": f'{sys.executable} -c "import time; time.sleep(120)"'},
        project=tmp_path,
    )
    holder: dict[str, object] = {}
    worker = threading.Thread(target=lambda: holder.setdefault("result", run_once(store)))

    worker.start()
    runtime = TaskRuntime(store)

    # Wait for the child to actually be running before cancelling it. How long
    # that takes depends on machine load and says nothing about cancellation,
    # so it is deliberately not part of the latency budget below, and the grace
    # period is generous: a ten-second cap failed here about once in twenty-five
    # runs, with the task still sitting in "queued".
    deadline = time.monotonic() + STARTUP_GRACE_SECONDS
    while time.monotonic() < deadline:
        task = runtime.get(queued["execution_task_id"])
        if task and task["state"] == "running":
            break
        time.sleep(0.02)
    assert runtime.get(queued["execution_task_id"])["state"] == "running"

    # The point of the test: cancelling interrupts the child instead of waiting
    # out its sleep. The child sleeps for two minutes and the budget is fifteen
    # seconds, so the gap is structural rather than a stopwatch reading. An
    # earlier version slept ten seconds and allowed five, which left so little
    # headroom that ordinary machine load failed it roughly one run in five.
    # Measure from the cancel, not from the thread start: a slow start says
    # nothing about cancellation.
    cancelled_at = time.monotonic()
    runtime.cancel(queued["execution_task_id"])
    worker.join(timeout=CANCEL_BUDGET_SECONDS)

    assert not worker.is_alive()
    assert time.monotonic() - cancelled_at < CANCEL_BUDGET_SECONDS
    assert runtime.get(queued["execution_task_id"])["state"] == "cancelled"
    assert list_queue(store)["tasks"][0]["status"] == "cancelled"
    assert holder["result"]["results"][0]["result"]["cancelled"] is True
