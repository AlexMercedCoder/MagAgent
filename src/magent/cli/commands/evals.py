"""Local eval command registrations."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
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
        provider: str = typer.Option("", "--provider", help="Provider for real-agent suites."),
        model: str = typer.Option("", "--model", help="Model for real-agent suites."),
        timeout: int = typer.Option(180, "--timeout", min=1, help="Per-task timeout in seconds."),
        report_out: str = typer.Option("", "--report-out", help="Write the report as JSON."),
        keep_workspaces: bool = typer.Option(False, "--keep-workspaces"),
    ) -> None:
        """Run a verification suite or isolated real-agent task suite."""
        from magent.evals import compare_eval_runs, run_eval_suite

        suite_path = Path(suite)
        if not suite_path.is_absolute():
            suite_path = Path(project).resolve() / suite_path
        raw = json.loads(suite_path.read_text(encoding="utf-8"))
        is_agent_suite = raw.get("schema") == "magent.agent-eval.v1"
        if is_agent_suite:
            from magent.agent_evals import run_agent_eval_suite, write_agent_eval_report

            report = run_agent_eval_suite(
                project,
                suite_path,
                store=store(),
                provider_id=provider,
                model=model,
                timeout_seconds=timeout,
                keep_workspaces=keep_workspaces,
            )
            if report_out:
                report["report_path"] = write_agent_eval_report(report, report_out)
        else:
            report = run_eval_suite(project, suite_path, store=store())
        if not compare:
            console.print_json(data=report)
            raise typer.Exit(0 if report.get("ok") else 1)

        comparison = compare_eval_runs(
            store(),
            report["suite"],
            compare,
            collection="agent_eval_runs" if is_agent_suite else "eval_runs",
        )
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
        memory_dir: str = typer.Option("", "--memory-dir", help="Evaluate a fixture graph."),
        project: str = typer.Option("", "--project", help="Expected project scope."),
        report_out: str = typer.Option("", "--report-out", help="Write the JSON report."),
    ) -> None:
        """Measure recall precision, stale hits, explanations, and context budget."""
        from magent.config import get_current_user, user_memory_dir
        from magent.memory import MemoryManager
        from magent.memory_evals import run_memory_eval

        username = user or get_current_user() or "default"
        root = Path(memory_dir).expanduser().resolve() if memory_dir else user_memory_dir(username)
        manager = MemoryManager(root, username=username, project_slug=project or None)
        report = run_memory_eval(manager, suite)
        if report_out:
            target = Path(report_out).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            report["report_path"] = str(target)
        console.print_json(data=report)
        raise typer.Exit(0 if report["ok"] else 1)
