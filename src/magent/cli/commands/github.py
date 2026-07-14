"""GitHub workflow command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_github_commands(github_app: typer.Typer) -> None:
    @github_app.command("status")
    def github_status_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """Check gh availability and authentication."""
        from magent.github_workflows import github_status

        console.print_json(data=github_status(project))

    @github_app.command("issues")
    def github_issues_cmd(
        project: str = typer.Option(".", "--project", "-p"),
        limit: int = typer.Option(20, "--limit", "-n"),
        state: str = typer.Option("open", "--state"),
    ) -> None:
        """List GitHub issues with gh."""
        from magent.github_workflows import list_issues

        console.print_json(data=list_issues(project, limit=limit, state=state))

    @github_app.command("prs")
    def github_prs_cmd(
        project: str = typer.Option(".", "--project", "-p"),
        limit: int = typer.Option(20, "--limit", "-n"),
        state: str = typer.Option("open", "--state"),
    ) -> None:
        """List GitHub pull requests with gh."""
        from magent.github_workflows import list_prs

        console.print_json(data=list_prs(project, limit=limit, state=state))

    @github_app.command("issue")
    def github_issue_cmd(
        number: int = typer.Argument(...),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Show one GitHub issue with gh."""
        from magent.github_workflows import show_issue

        console.print_json(data=show_issue(project, number))

    @github_app.command("pr")
    def github_pr_cmd(
        number: int = typer.Argument(...),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Show one GitHub pull request with gh."""
        from magent.github_workflows import show_pr

        console.print_json(data=show_pr(project, number))

    @github_app.command("checks")
    def github_checks_cmd(
        number: int | None = typer.Argument(None),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Show pull request checks with gh."""
        from magent.github_workflows import pr_checks

        console.print_json(data=pr_checks(project, number))
