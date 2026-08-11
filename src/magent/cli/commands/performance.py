"""Performance diagnostics command registrations."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register_performance_commands(performance_app: typer.Typer) -> None:
    @performance_app.command("budget")
    def performance_budget_cmd(
        project: str = typer.Option(".", "--project", "-p"),
        profile: str = typer.Option("quick", "--profile", help="quick or release"),
        report_out: str = typer.Option("", "--report-out", help="Write JSON evidence."),
    ) -> None:
        """Run daily-driver performance gates on this machine."""
        from magent.cli.command_context import require_user, store
        from magent.performance import performance_budget

        try:
            result = performance_budget(store(), require_user(), project, profile=profile)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--profile") from exc
        if report_out:
            target = Path(report_out).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            result["report_path"] = str(target)
        console.print_json(data=result)
        raise typer.Exit(0 if result["ok"] else 1)

    @performance_app.command("install-shape")
    def performance_install_shape_cmd(
        samples: int = typer.Option(3, "--samples", min=1, max=10),
    ) -> None:
        """Measure installed package size and cold CLI startup cost."""
        from magent.performance import install_shape

        console.print_json(data=install_shape(samples))

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
