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


def test_running_daemon_process_observes_durable_cancellation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queued = enqueue_task(
        store,
        "shell",
        {"command": f'{sys.executable} -c "import time; time.sleep(10)"'},
        project=tmp_path,
    )
    holder: dict[str, object] = {}
    worker = threading.Thread(target=lambda: holder.setdefault("result", run_once(store)))

    started = time.monotonic()
    worker.start()
    runtime = TaskRuntime(store)
    deadline = started + 2
    while time.monotonic() < deadline:
        task = runtime.get(queued["execution_task_id"])
        if task and task["state"] == "running":
            break
        time.sleep(0.02)
    runtime.cancel(queued["execution_task_id"])
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert time.monotonic() - started < 2
    assert runtime.get(queued["execution_task_id"])["state"] == "cancelled"
    assert list_queue(store)["tasks"][0]["status"] == "cancelled"
    assert holder["result"]["results"][0]["result"]["cancelled"] is True
