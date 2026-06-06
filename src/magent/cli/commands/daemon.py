"""Daemon queue command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_daemon_commands(daemon_app: typer.Typer) -> None:
    @daemon_app.command("enqueue")
    def daemon_enqueue_cmd(
        kind: str = typer.Argument(...),
        value: str = typer.Argument(...),
        project: str = typer.Option(".", "--project", "-p"),
        run_at: str = typer.Option("", "--run-at"),
    ) -> None:
        """Enqueue an ask, recipe, plan, or shell task."""
        from magent.cli.command_context import store
        from magent.daemon import enqueue_task

        payload_key = {"recipe": "name", "plan": "id", "shell": "command"}.get(kind, "task")
        console.print_json(data=enqueue_task(store(), kind, {payload_key: value}, project=project, run_at=run_at))

    @daemon_app.command("list")
    def daemon_list_cmd(status: str = typer.Option("", "--status")) -> None:
        """List durable daemon queue tasks."""
        from magent.cli.command_context import store
        from magent.daemon import list_queue

        console.print_json(data=list_queue(store(), status=status))

    @daemon_app.command("run-once")
    def daemon_run_once_cmd(limit: int = typer.Option(1, "--limit", "-n")) -> None:
        """Run due queued tasks once."""
        from magent.cli.command_context import store
        from magent.daemon import enqueue_due_followups, run_once

        workbench = store()
        enqueue_due_followups(workbench)
        console.print_json(data=run_once(workbench, limit=limit))

    @daemon_app.command("start")
    def daemon_start_cmd(limit: int = typer.Option(1, "--limit", "-n")) -> None:
        """Foreground worker alias for `run-once`."""
        from magent.cli.command_context import store
        from magent.daemon import enqueue_due_followups, run_once

        workbench = store()
        enqueue_due_followups(workbench)
        console.print_json(data=run_once(workbench, limit=limit))
