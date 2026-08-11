"""Durable local background queue and worker helpers."""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent.task_runtime import TaskRuntime

QUEUE_STORE = "daemon_queue"


def enqueue_task(
    store: Any,
    kind: str,
    payload: dict[str, Any],
    *,
    project: str | Path = ".",
    run_at: str = "",
) -> dict[str, Any]:
    runtime_task = TaskRuntime(store).create(
        kind,
        _task_title(kind, payload),
        project=project,
        metadata={"source": "daemon", "run_at": run_at},
    )
    item: dict[str, Any] = store.append(
        QUEUE_STORE,
        {
            "kind": kind,
            "payload": payload,
            "project": str(Path(project).resolve()),
            "run_at": run_at,
            "status": "pending",
            "attempts": 0,
            "execution_task_id": runtime_task["id"],
        },
    )
    return item


def list_queue(store: Any, status: str = "") -> dict[str, Any]:
    items = list(reversed(store.read(QUEUE_STORE, [])))
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"ok": True, "tasks": items}


def _claim_next(store: Any, runtime: Any, now: datetime) -> dict[str, Any] | None:
    """Atomically claim one due task, or return None.

    run_once used to read the whole queue, mark items running only in memory,
    execute them (potentially for ten minutes), and write state back once at
    the end. A second worker saw those items still `pending` and ran them
    again, and a crash mid-batch lost every result.
    """

    def claim(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        for item in items:
            if item.get("status") != "pending" or not _due(item, now):
                continue

            execution_task_id = str(item.get("execution_task_id") or "")
            runtime_task = runtime.get(execution_task_id) if execution_task_id else None
            if runtime_task and runtime_task["state"] in {"cancelled", "waiting"}:
                continue
            if not runtime_task:
                runtime_task = runtime.create(
                    str(item.get("kind") or "ask"),
                    _task_title(str(item.get("kind") or "ask"), item.get("payload") or {}),
                    project=item.get("project") or ".",
                    metadata={"source": "daemon", "legacy_queue_id": item.get("id", "")},
                )
                item["execution_task_id"] = runtime_task["id"]

            # The claim is persisted before we return, so a concurrent worker
            # sees "running" rather than a second chance to execute it.
            item["status"] = "running"
            item["attempts"] = int(item.get("attempts") or 0) + 1
            item["updated_at"] = datetime.now(UTC).isoformat()
            return items, dict(item)
        return items, None

    return store.mutate(QUEUE_STORE, [], claim)


def _record_outcome(store: Any, task_id: str, updates: dict[str, Any]) -> None:
    """Persist one item's outcome immediately, not at the end of the batch."""

    def apply(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in items:
            if item.get("id") == task_id:
                item.update(updates)
                item["updated_at"] = datetime.now(UTC).isoformat()
        return items

    store.mutate(QUEUE_STORE, [], apply)


def run_once(store: Any, *, limit: int = 1) -> dict[str, Any]:
    runtime = TaskRuntime(store)
    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    while len(results) < limit:
        item = _claim_next(store, runtime, now)
        if item is None:
            break

        task_id = str(item.get("id") or "")
        execution_task_id = str(item.get("execution_task_id") or "")

        # An illegal transition used to raise out of the loop, so the final
        # write never happened and every completed item in the batch re-ran.
        with contextlib.suppress(Exception):
            runtime.transition(execution_task_id, "running", detail={"queue_id": task_id})

        try:

            def control_state(task_id: str = execution_task_id) -> str:
                return str((runtime.get(task_id) or {}).get("state", ""))

            result = _execute_item(item, control_state=control_state)
        except Exception as exc:  # never leave an item stuck in "running"
            result = {"ok": False, "error": str(exc)}

        if result.get("cancelled"):
            status = "cancelled"
        elif result.get("paused"):
            status = "pending"
        else:
            status = "done" if result.get("ok") else "failed"

        item["status"] = status
        item["result"] = result
        # try/finally in spirit: the outcome is written per item, so a crash
        # in the next iteration cannot roll this one back to pending.
        _record_outcome(store, task_id, {"status": status, "result": result})

        with contextlib.suppress(Exception):
            runtime.update_context(
                execution_task_id,
                final_audit={"ok": bool(result.get("ok")), "returncode": result.get("returncode")},
                metadata={"queue_status": status},
            )
            if not result.get("cancelled") and not result.get("paused"):
                runtime.transition(
                    execution_task_id,
                    "completed" if result.get("ok") else "failed",
                    detail={"queue_id": task_id},
                )

        results.append({"task": item, "result": result})

    return {
        # all([]) is True: an empty run used to report success when nothing ran.
        "ok": bool(results) and all(entry["result"].get("ok") for entry in results),
        "ran": len(results),
        "results": results,
    }


def enqueue_due_followups(store: Any) -> dict[str, Any]:
    followups = store.read("followups", [])
    created = []
    now = datetime.now(UTC)
    # Anything already dealt with stays dealt with. Only "queued" was skipped,
    # so a followup that had been run, cancelled or failed was re-enqueued on
    # every pass, forever.
    settled = {"queued", "done", "completed", "cancelled", "failed", "dismissed", "skipped"}
    for item in followups:
        if str(item.get("status") or "") in settled:
            continue
        run_at = item.get("when") or item.get("run_at") or ""
        if run_at and not _time_due(run_at, now):
            continue
        task = enqueue_task(
            store,
            "ask",
            {"task": item.get("text", ""), "source": f"followup/{item.get('id', '')}"},
            run_at=run_at,
        )
        item["status"] = "queued"
        created.append(task)
    store.write("followups", followups)
    return {"ok": True, "queued": created}


def _due(item: dict[str, Any], now: datetime) -> bool:
    run_at = item.get("run_at") or ""
    return not run_at or _time_due(run_at, now)


def _time_due(raw: str, now: datetime) -> bool:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= now


def _execute_item(
    item: dict[str, Any], *, control_state: Callable[[], str] | None = None
) -> dict[str, Any]:
    kind = item.get("kind")
    payload = item.get("payload", {})
    project = item.get("project") or "."
    if kind == "recipe":
        command = ["magent", "recipe", "run", payload.get("name", ""), "--project", project]
    elif kind == "orchestrated_goal":
        command = ["magent", "goal-run", payload.get("id", ""), "--project", project, "--json"]
    elif kind == "agraph":
        command = [
            "magent",
            "graph",
            "run",
            payload.get("path", ""),
            "--project",
            project,
            "--json",
        ]
        if payload.get("yes"):
            command.append("--yes")
    elif kind == "plan":
        command = ["magent", "plan-apply", payload.get("id", ""), "--yes"]
    elif kind == "shell":
        return _run_shell(payload.get("command", ""), project, control_state=control_state)
    else:
        command = ["magent", "ask", payload.get("task", ""), "--project", project]
    return _run_command(command, project, control_state=control_state)


def _run_shell(
    command: str,
    project: str | Path,
    *,
    control_state: Callable[[], str] | None = None,
) -> dict[str, Any]:
    if not command:
        return {"ok": False, "error": "Empty shell task"}
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return {"ok": False, "command": command, "error": str(e)}

    # Anything that can write the daemon_queue store could previously run
    # arbitrary local commands: this path went straight to shlex.split + Popen
    # with no classification at all.
    from magent.command_policy import command_policy

    policy = command_policy(command)
    if not policy["ok"]:
        return {
            "ok": False,
            "command": command,
            "tier": policy["tier"],
            "blocked": True,
            "error": "Blocked by MagAgent command policy",
        }
    return _run_command(argv, project, control_state=control_state)


def _terminate_group(process: subprocess.Popen[Any], *, force: bool = False) -> None:
    """Signal the whole process group.

    `start_new_session=True` puts the child in its own group, but terminate()
    and kill() only reach the leader — a shell task's children carried on
    running after a cancel or a timeout.
    """
    try:
        group = os.getpgid(process.pid)
    except (AttributeError, ProcessLookupError, OSError):
        group = None

    def signal_all(sig: int) -> None:
        if group is not None:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(group, sig)
                return
        with contextlib.suppress(Exception):
            process.kill() if sig == signal.SIGKILL else process.terminate()

    if not force:
        signal_all(signal.SIGTERM)
        try:
            process.wait(timeout=1.0)
            return
        except subprocess.TimeoutExpired:
            pass
    signal_all(signal.SIGKILL)
    with contextlib.suppress(Exception):
        process.wait(timeout=2.0)


def _run_command(
    command: list[str],
    project: str | Path,
    *,
    control_state: Callable[[], str] | None = None,
) -> dict[str, Any]:
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                command,
                cwd=project,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            started = time.monotonic()
            requested = ""
            while process.poll() is None:
                state = str(control_state() if control_state else "")
                if state in {"cancelled", "waiting"}:
                    requested = state
                    _terminate_group(process)
                    break
                if time.monotonic() - started >= 600:
                    _terminate_group(process, force=True)
                    requested = "timeout"
                    break
                time.sleep(0.1)
            returncode = process.wait()
            stdout.seek(0)
            stderr.seek(0)
            output = stdout.read().decode("utf-8", errors="replace")[-8000:]
            errors = stderr.read().decode("utf-8", errors="replace")[-4000:]
            return {
                "ok": returncode == 0 and not requested,
                "command": " ".join(command),
                "returncode": returncode,
                "stdout": output,
                "stderr": errors,
                "cancelled": requested == "cancelled",
                "paused": requested == "waiting",
                "timed_out": requested == "timeout",
            }
    except Exception as e:
        return {"ok": False, "command": " ".join(command), "error": str(e)}


def _task_title(kind: str, payload: dict[str, Any]) -> str:
    for key in ("task", "name", "command", "id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value[:500]
    return f"Background {kind} task"
