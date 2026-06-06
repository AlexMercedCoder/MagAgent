"""Workbench maintenance command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_workbench_commands(workbench_app: typer.Typer) -> None:
    @workbench_app.command("stats")
    def workbench_stats_cmd() -> None:
        """Show workbench store sizes and maintenance recommendations."""
        from magent.cli.command_context import store
        from magent.workbench_maintenance import workbench_stats

        console.print_json(data=workbench_stats(store()))

    @workbench_app.command("prune")
    def workbench_prune_cmd(
        older_than_days: int = typer.Option(30, "--older-than-days"),
        keep: int | None = typer.Option(None, "--keep"),
        dry_run: bool = typer.Option(False, "--dry-run"),
    ) -> None:
        """Prune old high-volume workbench records."""
        from magent.cli.command_context import store
        from magent.workbench_maintenance import prune_workbench

        console.print_json(
            data=prune_workbench(
                store(),
                older_than_days=older_than_days,
                keep=keep,
                dry_run=dry_run,
            )
        )

    @workbench_app.command("compact")
    def workbench_compact_cmd() -> None:
        """Rewrite JSON stores and report bytes reclaimed."""
        from magent.cli.command_context import store
        from magent.workbench_maintenance import compact_workbench

        console.print_json(data=compact_workbench(store()))
