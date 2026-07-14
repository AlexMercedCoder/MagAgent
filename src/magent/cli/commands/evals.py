"""Local eval command registrations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console

console = Console()


def register_eval_commands(eval_app: typer.Typer, *, store: Callable[[], Any]) -> None:
    @eval_app.command("init")
    def eval_init_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """Create a starter local eval suite."""
        from magent.evals import init_evals

        console.print_json(data=init_evals(project))

    @eval_app.command("list")
    def eval_list_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """List local eval suites."""
        from magent.evals import list_eval_suites

        console.print_json(data={"ok": True, "suites": list_eval_suites(project)})

    @eval_app.command("run")
    def eval_run_cmd(
        suite: str = typer.Argument("evals/magagent-evals.json"),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Run a local eval suite's verification commands."""
        from magent.evals import run_eval_suite

        console.print_json(data=run_eval_suite(project, suite, store=store()))

    @eval_app.command("report")
    def eval_report_cmd(limit: int = typer.Option(20, "--limit", "-n")) -> None:
        """Show recent eval run reports."""
        from magent.evals import eval_report

        console.print_json(data={"ok": True, "runs": eval_report(store(), limit=limit)})
