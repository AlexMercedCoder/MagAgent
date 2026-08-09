"""Adapters between live agent sessions and the durable task runtime."""

from __future__ import annotations

from typing import Any

from magent.session_controls import session_usage
from magent.task_runtime import TaskRuntime, TaskRuntimeError, TaskState
from magent.workbench_store import WorkbenchStore


class SessionTaskBridge:
    """Mirror a live AgentSession into one durable execution task."""

    def __init__(
        self,
        store: WorkbenchStore,
        session: Any,
        *,
        kind: str,
        title: str,
        project: str,
        permission_policy: str,
        provider: Any,
        task_id: str = "",
        parent_task_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.runtime = TaskRuntime(store)
        self.session = session
        task_metadata = {
            "provider": getattr(provider, "provider_id", ""),
            "model": getattr(provider, "model", ""),
            **(metadata or {}),
        }
        if task_id:
            existing = self.runtime.get(task_id)
            if not existing:
                raise TaskRuntimeError(f"Task not found: {task_id}")
            self.task = self.runtime.update_context(task_id, metadata=task_metadata)
        else:
            self.task = self.runtime.create(
                kind,
                title,
                project=project,
                session_id=str(session.session_id),
                parent_task_id=parent_task_id,
                execution_role="coding",
                permission_policy=permission_policy,
                metadata=task_metadata,
            )
        self.task_id = str(self.task["id"])
        session.execution_task_id = self.task_id
        self._closed = False
        logger = getattr(session, "logger", None)
        if logger and hasattr(logger, "set_event_callback"):
            logger.set_event_callback(self._forward_record)
        self.runtime.transition(self.task_id, "running", reason="Agent session started")

    def event(self, event_type: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.runtime.record_event(self.task_id, event_type, detail=detail or {})

    def complete(self, audit: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist session evidence and close the task truthfully."""
        if self._closed:
            return self.runtime.get(self.task_id) or self.task
        final_audit = audit or {"ok": True}
        self.runtime.transition(self.task_id, "validating", reason="Session audit started")
        self._persist_evidence(final_audit)
        state: TaskState = "completed" if final_audit.get("ok", True) else "blocked"
        result = self.runtime.transition(
            self.task_id,
            state,
            reason="Session audit passed" if state == "completed" else "Session needs attention",
        )
        self._closed = True
        self._detach()
        return result

    def fail(self, error: BaseException | str) -> dict[str, Any]:
        if self._closed:
            return self.runtime.get(self.task_id) or self.task
        message = str(error) or type(error).__name__
        self._persist_evidence({"ok": False, "error": message})
        result = self.runtime.transition(self.task_id, "failed", reason=message)
        self._closed = True
        self._detach()
        return result

    def _detach(self) -> None:
        logger = getattr(self.session, "logger", None)
        if logger and hasattr(logger, "set_event_callback"):
            logger.set_event_callback(None)

    def _persist_evidence(self, final_audit: dict[str, Any]) -> None:
        logger = getattr(self.session, "logger", None)
        usage = session_usage(logger.path) if logger and hasattr(logger, "path") else {}
        scratchpad = getattr(self.session, "scratchpad", {}) or {}
        self.runtime.update_context(
            self.task_id,
            usage={
                key: usage[key]
                for key in (
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "cached_tokens",
                    "cost_usd",
                )
                if key in usage
            },
            files_changed=[str(path) for path in scratchpad.get("files_touched", [])],
            final_audit=final_audit,
            metadata={
                "commands_run": scratchpad.get("commands_run", []),
                "permission_failures": scratchpad.get("permission_failures", []),
                "turns": int(getattr(self.session, "turn_count", 0) or 0),
            },
        )

    def _forward_record(self, record: dict[str, Any]) -> None:
        self.runtime.record_event(
            self.task_id,
            f"session.{record.get('event', 'activity')}",
            detail={
                key: value
                for key, value in record.items()
                if key not in {"event", "session", "user"}
            },
        )
