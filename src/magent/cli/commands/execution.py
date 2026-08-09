"""Machine-readable commands for durable execution tasks."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from magent.task_runtime import TASK_STATES, TaskRuntime, TaskRuntimeError, TaskState
from magent.workbench_store import WorkbenchStore


def register_execution_commands(
    execution_app: typer.Typer,
    *,
    store: Callable[[], WorkbenchStore],
    console: Console,
) -> None:
    """Register the versioned task-runtime command surface."""

    @execution_app.command("create")  # type: ignore[untyped-decorator]
    def create_cmd(
        title: str = typer.Argument(...),
        kind: str = typer.Option("ask", "--kind"),
        project: str = typer.Option(".", "--project", "-p"),
        session_id: str = typer.Option("", "--session"),
        parent_task_id: str = typer.Option("", "--parent"),
        planning_role: str = typer.Option("", "--planning-role"),
        execution_role: str = typer.Option("", "--execution-role"),
        permission_policy: str = typer.Option("", "--permission-policy"),
    ) -> None:
        """Create a queued execution task."""
        task = TaskRuntime(store()).create(
            kind,
            title,
            project=Path(project),
            session_id=session_id,
            parent_task_id=parent_task_id,
            planning_role=planning_role,
            execution_role=execution_role,
            permission_policy=permission_policy,
        )
        console.print_json(data={"ok": True, "task": task})

    @execution_app.command("list")  # type: ignore[untyped-decorator]
    def list_cmd(
        state: str = typer.Option("", "--state", help=f"One of: {', '.join(TASK_STATES)}"),
        project_id: str = typer.Option("", "--project-id"),
        parent_task_id: str | None = typer.Option(None, "--parent"),
        limit: int = typer.Option(100, "--limit", "-n", min=1, max=1000),
    ) -> None:
        """List durable execution tasks as JSON."""
        parsed_state = _state(state) if state else None
        tasks = TaskRuntime(store()).list_tasks(
            state=parsed_state,
            project_id=project_id,
            parent_task_id=parent_task_id,
            limit=limit,
        )
        console.print_json(data={"ok": True, "tasks": tasks})

    @execution_app.command("show")  # type: ignore[untyped-decorator]
    def show_cmd(task_id: str = typer.Argument(...)) -> None:
        """Show one durable execution task as JSON."""
        task = TaskRuntime(store()).get(task_id)
        if task is None:
            _fail(f"Task not found: {task_id}", console)
        console.print_json(data={"ok": True, "task": task})

    @execution_app.command("events")  # type: ignore[untyped-decorator]
    def events_cmd(
        task_id: str = typer.Argument(...),
        after: int = typer.Option(0, "--after", min=0),
        limit: int = typer.Option(500, "--limit", "-n", min=1, max=5000),
        jsonl: bool = typer.Option(False, "--jsonl", help="Emit one event per line."),
    ) -> None:
        """Read ordered task events as JSON or JSONL."""
        runtime = TaskRuntime(store())
        if runtime.get(task_id) is None:
            _fail(f"Task not found: {task_id}", console)
        events = runtime.events(task_id, after=after, limit=limit)
        if jsonl:
            for event in events:
                typer.echo(json.dumps(event, separators=(",", ":"), default=str))
            return
        console.print_json(data={"ok": True, "events": events})

    def transition_command(task_id: str, action: str, reason: str) -> None:
        runtime = TaskRuntime(store())
        try:
            operation = getattr(runtime, action)
            task = operation(task_id, reason=reason)
        except TaskRuntimeError as exc:
            _fail(str(exc), console)
        console.print_json(data={"ok": True, "task": task})

    @execution_app.command("pause")  # type: ignore[untyped-decorator]
    def pause_cmd(
        task_id: str = typer.Argument(...), reason: str = typer.Option("Paused by user", "--reason")
    ) -> None:
        """Move a running task into the waiting state."""
        transition_command(task_id, "pause", reason)

    @execution_app.command("resume")  # type: ignore[untyped-decorator]
    def resume_cmd(
        task_id: str = typer.Argument(...),
        reason: str = typer.Option("Resumed by user", "--reason"),
    ) -> None:
        """Resume a waiting or blocked task."""
        transition_command(task_id, "resume", reason)

    @execution_app.command("cancel")  # type: ignore[untyped-decorator]
    def cancel_cmd(
        task_id: str = typer.Argument(...),
        reason: str = typer.Option("Cancelled by user", "--reason"),
    ) -> None:
        """Cancel an active execution task."""
        transition_command(task_id, "cancel", reason)

    @execution_app.command("retry")  # type: ignore[untyped-decorator]
    def retry_cmd(
        task_id: str = typer.Argument(...),
        reason: str = typer.Option("Retried by user", "--reason"),
    ) -> None:
        """Queue a blocked, failed, completed, or cancelled task for another attempt."""
        transition_command(task_id, "retry", reason)


def _state(raw: str) -> TaskState:
    if raw not in TASK_STATES:
        raise typer.BadParameter(f"state must be one of: {', '.join(TASK_STATES)}")
    return raw


def _fail(message: str, console: Console) -> Any:
    console.print_json(data={"ok": False, "error": message})
    raise typer.Exit(1)
