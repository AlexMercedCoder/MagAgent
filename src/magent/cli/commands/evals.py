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
        compare: str = typer.Option(
            "", "--compare", help="Compare against the last recorded run at this version."
        ),
    ) -> None:
        """Run a local eval suite's verification commands."""
        from magent.evals import compare_eval_runs, run_eval_suite

        report = run_eval_suite(project, suite, store=store())
        if not compare:
            console.print_json(data=report)
            raise typer.Exit(0 if report.get("ok") else 1)

        comparison = compare_eval_runs(store(), report["suite"], compare)
        console.print_json(data={"run": report, "comparison": comparison})
        # A regression against the baseline fails the command even if the run
        # itself passed more tasks than it failed.
        raise typer.Exit(0 if report.get("ok") and comparison.get("ok") else 1)

    @eval_app.command("report")
    def eval_report_cmd(limit: int = typer.Option(20, "--limit", "-n")) -> None:
        """Show recent eval run reports."""
        from magent.evals import eval_report

        console.print_json(data={"ok": True, "runs": eval_report(store(), limit=limit)})

    @eval_app.command("memory")
    def eval_memory_cmd(
        suite: str = typer.Argument(..., help="Labeled memory eval JSON file."),
        user: str | None = typer.Option(None, "--user", "-u"),
    ) -> None:
        """Measure recall precision, stale hits, explanations, and context budget."""
        from magent.config import get_current_user, user_memory_dir
        from magent.memory import MemoryManager
        from magent.memory_evals import run_memory_eval

        username = user or get_current_user() or "default"
        manager = MemoryManager(user_memory_dir(username), username=username)
        console.print_json(data=run_memory_eval(manager, suite))
