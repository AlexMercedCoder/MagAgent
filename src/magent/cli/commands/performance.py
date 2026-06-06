"""Performance diagnostics command registrations."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register_performance_commands(performance_app: typer.Typer) -> None:
    @performance_app.command("doctor")
    def performance_doctor_cmd(
        project: str = typer.Option(".", "--project", "-p"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Inspect startup, repo, workbench, memory, and config performance."""
        from magent.cli.command_context import require_user, store
        from magent.performance import performance_doctor

        result = performance_doctor(store(), require_user(), project)
        if json_output:
            console.print_json(data=result)
            return
        table = Table("Area", "Value")
        table.add_row("Project", result["project"])
        table.add_row("Repo files seen", str(result["repo"]["files_seen"]))
        table.add_row("Workbench bytes", str(result["workbench"]["total_bytes"]))
        table.add_row("Semantic chunks", str(result["semantic_memory"].get("chunks", 0)))
        for name, value in result["timings_ms"].items():
            table.add_row(name, f"{value} ms")
        console.print(table)
        if result["recommendations"]:
            console.print_json(data={"recommendations": result["recommendations"]})
