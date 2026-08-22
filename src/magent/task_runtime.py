"""Durable, versioned execution tasks and append-only lifecycle events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Literal, cast

from magent.workbench_store import WorkbenchStore

TASK_SCHEMA_VERSION = "magent.task.v2"
EVENT_SCHEMA_VERSION = "magent.task-event.v1"
_INITIALIZE_LOCK = Lock()

TaskState = Literal[
    "pending",
    "ready",
    "queued",
    "planning",
    "running",
    "waiting",
    "awaiting_human",
    "blocked",
    "validating",
    "completed",
    "succeeded",
    "failed",
    "cancelled",
    "skipped",
]

TASK_STATES: tuple[TaskState, ...] = (
    "pending",
    "ready",
    "queued",
    "planning",
    "running",
    "waiting",
    "awaiting_human",
    "blocked",
    "validating",
    "completed",
    "succeeded",
    "failed",
    "cancelled",
    "skipped",
)

_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    "pending": frozenset({"ready", "blocked", "cancelled", "skipped"}),
    "ready": frozenset({"running", "blocked", "cancelled", "skipped"}),
    "queued": frozenset({"planning", "running", "cancelled"}),
    "planning": frozenset({"running", "waiting", "blocked", "failed", "cancelled"}),
    "running": frozenset({"waiting", "awaiting_human", "blocked", "validating", "completed", "succeeded", "failed", "cancelled", "skipped"}),
    "waiting": frozenset({"running", "blocked", "failed", "cancelled"}),
    "awaiting_human": frozenset({"running", "blocked", "failed", "cancelled"}),
    "blocked": frozenset({"queued", "ready", "running", "failed", "cancelled"}),
    "validating": frozenset({"running", "blocked", "completed", "succeeded", "failed", "cancelled"}),
    "completed": frozenset({"queued"}),
    "succeeded": frozenset({"queued"}),
    "failed": frozenset({"queued", "blocked", "cancelled"}),
    "cancelled": frozenset({"queued"}),
    "skipped": frozenset({"queued"}),
}


class TaskRuntimeError(ValueError):
    """Raised when a durable task operation cannot be applied."""


class TaskRuntime:
    """SQLite task ledger shared by CLI, daemon, goals, and desktop clients."""

    def __init__(self, store: WorkbenchStore | str | Path):
        root = store.root if isinstance(store, WorkbenchStore) else Path(store)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "task_runtime.sqlite3"
        # Journal mode persists in the database. Set it once instead of taking
        # the journal lock again for every short-lived event connection.
        # Multiple graph/card workers can discover the ledger simultaneously.
        # Serialize one-time WAL/schema setup inside the process; normal reads
        # and writes remain independently connected and concurrency-safe.
        with _INITIALIZE_LOCK:
            connection = sqlite3.connect(self.path, timeout=60)
            try:
                connection.execute("PRAGMA busy_timeout = 60000")
                connection.execute("PRAGMA journal_mode = WAL")
            finally:
                connection.close()
            self._initialize()

    def create(
        self,
        kind: str,
        title: str,
        *,
        project: str | Path = ".",
        project_id: str = "",
        session_id: str = "",
        parent_task_id: str = "",
        planning_role: str = "",
        execution_role: str = "",
        permission_policy: str = "",
        state: TaskState = "queued",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a durable task and its first event in one transaction."""
        if state not in TASK_STATES:
            raise TaskRuntimeError(f"Unknown task state: {state}")
        project_path = str(Path(project).resolve())
        task_id = f"task_{uuid.uuid4().hex[:16]}"
        now = _now()
        task = {
            "id": task_id,
            "schema_version": TASK_SCHEMA_VERSION,
            "kind": str(kind)[:80],
            "title": str(title)[:500],
            "state": state,
            "project_id": project_id or _project_id(project_path),
            "project_path": project_path,
            "session_id": str(session_id)[:160],
            "parent_task_id": str(parent_task_id)[:160],
            "created_at": now,
            "updated_at": now,
            "started_at": now if state in {"running", "validating"} else "",
            "finished_at": now if state in {"completed", "succeeded", "failed", "cancelled", "skipped"} else "",
            "planning_role": str(planning_role)[:80],
            "execution_role": str(execution_role)[:80],
            "permission_policy": str(permission_policy)[:80],
            "attempt": 1,
            "usage": {},
            "files_changed": [],
            "checkpoints": [],
            "final_audit": {},
            "metadata": metadata or {},
        }
        with self._connect(write=True) as connection:
            self._insert_task(connection, task)
            self._append_event(
                connection, task_id, "task_created", state, {"kind": kind, "title": title}
            )
        return task

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_from_row(row) if row else None

    def list_tasks(
        self,
        *,
        state: TaskState | None = None,
        project_id: str = "",
        parent_task_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if state:
            clauses.append("state = ?")
            params.append(state)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if parent_task_id is not None:
            clauses.append("parent_task_id = ?")
            params.append(parent_task_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 1000)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks{where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
                params,
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def events(self, task_id: str, *, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence ASC LIMIT ?
                """,
                (task_id, max(0, after), max(1, min(limit, 5000))),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def record_event(
        self,
        task_id: str,
        event_type: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.record_events(
            task_id,
            [{"type": event_type, "detail": detail or {}}],
        )[0]

    def record_events(
        self,
        task_id: str,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Append a bounded event batch in one durable transaction."""
        if not events:
            return []
        if len(events) > 1000:
            raise TaskRuntimeError("Event batch exceeds the 1000-event limit")
        with self._connect(write=True) as connection:
            row = connection.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                raise TaskRuntimeError(f"Task not found: {task_id}")
            sequence_row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM task_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            sequence = int(sequence_row["sequence"])
            appended: list[dict[str, Any]] = []
            for item in events:
                sequence += 1
                raw_detail = item.get("detail")
                detail = raw_detail if isinstance(raw_detail, dict) else {}
                appended.append(
                    self._append_event(
                        connection,
                        task_id,
                        str(item.get("type") or "event"),
                        str(row["state"]),
                        detail,
                        sequence=sequence,
                    )
                )
            return appended

    def transition(
        self,
        task_id: str,
        state: TaskState,
        *,
        reason: str = "",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply a legal state transition and append its event atomically."""
        if state not in TASK_STATES:
            raise TaskRuntimeError(f"Unknown task state: {state}")
        with self._connect(write=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                raise TaskRuntimeError(f"Task not found: {task_id}")
            task = _task_from_row(row)
            current = cast(TaskState, task["state"])
            if state == current:
                return task
            if state not in _TRANSITIONS[current]:
                raise TaskRuntimeError(f"Illegal task transition: {current} -> {state}")
            now = _now()
            started_at = task["started_at"] or (now if state in {"running", "validating"} else "")
            finished_at = now if state in {"completed", "succeeded", "failed", "cancelled", "skipped"} else ""
            attempt = int(task["attempt"]) + (
                1
                if state == "queued" and current in {"blocked", "completed", "succeeded", "failed", "cancelled", "skipped"}
                else 0
            )
            connection.execute(
                """
                UPDATE tasks SET state = ?, updated_at = ?, started_at = ?, finished_at = ?, attempt = ?
                WHERE id = ?
                """,
                (state, now, started_at, finished_at, attempt, task_id),
            )
            event_detail = {**(detail or {})}
            if reason:
                event_detail["reason"] = str(reason)[:1000]
            self._append_event(connection, task_id, "state_changed", state, event_detail)
            updated = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_from_row(updated)

    def update_context(
        self,
        task_id: str,
        *,
        usage: dict[str, Any] | None = None,
        files_changed: list[str] | None = None,
        checkpoints: list[str] | None = None,
        final_audit: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge execution evidence into a task and emit a context event."""
        with self._connect(write=True) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                raise TaskRuntimeError(f"Task not found: {task_id}")
            task = _task_from_row(row)
            next_usage = {**task["usage"], **(usage or {})}
            next_files = _unique([*task["files_changed"], *(files_changed or [])])
            next_checkpoints = _unique([*task["checkpoints"], *(checkpoints or [])])
            next_audit = {**task["final_audit"], **(final_audit or {})}
            next_metadata = {**task["metadata"], **(metadata or {})}
            connection.execute(
                """
                UPDATE tasks SET updated_at = ?, usage_json = ?, files_json = ?, checkpoints_json = ?,
                    final_audit_json = ?, metadata_json = ? WHERE id = ?
                """,
                (
                    _now(),
                    _json(next_usage),
                    _json(next_files),
                    _json(next_checkpoints),
                    _json(next_audit),
                    _json(next_metadata),
                    task_id,
                ),
            )
            self._append_event(
                connection,
                task_id,
                "task_context_updated",
                task["state"],
                {
                    "usage": usage or {},
                    "files_changed": files_changed or [],
                    "checkpoints": checkpoints or [],
                    "final_audit": final_audit or {},
                    "metadata": metadata or {},
                },
            )
            updated = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _task_from_row(updated)

    def pause(self, task_id: str, reason: str = "Paused by user") -> dict[str, Any]:
        return self.transition(task_id, "waiting", reason=reason)

    def resume(self, task_id: str, reason: str = "Resumed by user") -> dict[str, Any]:
        return self.transition(task_id, "running", reason=reason)

    def cancel(self, task_id: str, reason: str = "Cancelled by user") -> dict[str, Any]:
        return self.transition(task_id, "cancelled", reason=reason)

    def retry(self, task_id: str, reason: str = "Retried by user") -> dict[str, Any]:
        return self.transition(task_id, "queued", reason=reason)

    def _initialize(self) -> None:
        with self._connect(write=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    state TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    project_path TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    parent_task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    planning_role TEXT NOT NULL,
                    execution_role TEXT NOT NULL,
                    permission_policy TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    usage_json TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    checkpoints_json TEXT NOT NULL,
                    final_audit_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state, updated_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id, created_at);
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    sequence INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    type TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    UNIQUE(task_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, sequence);
                """
            )

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=60)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 60000")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _insert_task(self, connection: sqlite3.Connection, task: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO tasks (
                id, schema_version, kind, title, state, project_id, project_path, session_id,
                parent_task_id, created_at, updated_at, started_at, finished_at, planning_role,
                execution_role, permission_policy, attempt, usage_json, files_json,
                checkpoints_json, final_audit_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["schema_version"],
                task["kind"],
                task["title"],
                task["state"],
                task["project_id"],
                task["project_path"],
                task["session_id"],
                task["parent_task_id"],
                task["created_at"],
                task["updated_at"],
                task["started_at"],
                task["finished_at"],
                task["planning_role"],
                task["execution_role"],
                task["permission_policy"],
                task["attempt"],
                _json(task["usage"]),
                _json(task["files_changed"]),
                _json(task["checkpoints"]),
                _json(task["final_audit"]),
                _json(task["metadata"]),
            ),
        )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        event_type: str,
        state: str,
        detail: dict[str, Any],
        *,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        if sequence is None:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM task_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            sequence = int(row["sequence"])
        event = {
            "event_id": f"evt_{uuid.uuid4().hex[:16]}",
            "task_id": task_id,
            "sequence": sequence,
            "schema_version": EVENT_SCHEMA_VERSION,
            "type": str(event_type)[:120],
            "ts": _now(),
            "state": state,
            "detail": detail,
        }
        connection.execute(
            "INSERT INTO task_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event["event_id"],
                task_id,
                sequence,
                event["schema_version"],
                event["type"],
                event["ts"],
                state,
                _json(detail),
            ),
        )
        return event


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "schema_version": row["schema_version"],
        "kind": row["kind"],
        "title": row["title"],
        "state": row["state"],
        "project_id": row["project_id"],
        "project_path": row["project_path"],
        "session_id": row["session_id"],
        "parent_task_id": row["parent_task_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "planning_role": row["planning_role"],
        "execution_role": row["execution_role"],
        "permission_policy": row["permission_policy"],
        "attempt": row["attempt"],
        "usage": _load_json(row["usage_json"], {}),
        "files_changed": _load_json(row["files_json"], []),
        "checkpoints": _load_json(row["checkpoints_json"], []),
        "final_audit": _load_json(row["final_audit_json"], {}),
        "metadata": _load_json(row["metadata_json"], {}),
    }


def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "task_id": row["task_id"],
        "sequence": row["sequence"],
        "schema_version": row["schema_version"],
        "type": row["type"],
        "ts": row["ts"],
        "state": row["state"],
        "detail": _load_json(row["detail_json"], {}),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _project_id(path: str) -> str:
    return f"project_{hashlib.sha256(path.encode()).hexdigest()[:16]}"


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _load_json(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item)))
