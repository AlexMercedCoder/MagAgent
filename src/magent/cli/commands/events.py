"""Workbench event log command registrations."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register_event_commands(events_app: typer.Typer) -> None:
    @events_app.command("list")
    def events_list_cmd(
        limit: int = typer.Option(50, "--limit", "-n"),
        kind: str = typer.Option("", "--kind"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """List recent workbench events."""
        from magent.cli.command_context import store
        from magent.events import list_events

        result = list_events(store(), limit=limit, kind=kind)
        if json_output:
            console.print_json(data=result)
            return
        table = Table("ID", "Kind", "Title", "Created")
        for event in result["events"]:
            table.add_row(
                event.get("id", ""),
                event.get("kind", ""),
                event.get("title", ""),
                event.get("created_at", ""),
            )
        console.print(table)

    @events_app.command("show")
    def events_show_cmd(event_id: str = typer.Argument(...)) -> None:
        """Show one workbench event."""
        from magent.cli.command_context import store
        from magent.events import show_event

        result = show_event(store(), event_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
