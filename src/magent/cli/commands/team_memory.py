"""`magent memory team ...`: shared MagGraph with review-gated merge."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table

from magent.cli import shared
from magent.cli.app import memory_app
from magent.cli.shared import console

team_app = typer.Typer(
    name="team",
    no_args_is_help=True,
    help=(
        "Share reviewed memory with a team (a Git repository of MagGraph nodes).\n\n"
        "Nodes reach the team graph only as proposals that a teammate accepts.\n\n"
        "Examples:\n\n"
        "  magent memory team init git@github.com:acme/team-memory.git\n\n"
        "  magent memory team init --create /shared/team-memory.git\n\n"
        "  magent memory team propose prefers_pytest -m 'Test runner convention'\n\n"
        "  magent memory team inbox\n\n"
        "  magent memory team show 3fa2c1d9e0\n\n"
        "  magent memory team accept 3fa2c1d9e0"
    ),
)
memory_app.add_typer(team_app, name="team")


def _team(name: str) -> Any:
    from magent.team_memory import TeamMemory, TeamMemoryError

    try:
        return TeamMemory(shared._require_user(), name=name)
    except TeamMemoryError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(2) from error


def _run(action: Any, json_output: bool, render: Any = None) -> Any:
    from magent.team_memory import TeamMemoryError

    try:
        result = action()
    except TeamMemoryError as error:
        if json_output:
            console.print_json(data={"ok": False, "error": str(error)})
        else:
            console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    if json_output or render is None:
        console.print_json(data=result)
    else:
        render(result)
    return result


NAME = typer.Option("team", "--name", help="Which team graph (default: team).")
JSON = typer.Option(False, "--json", help="Emit JSON.")


@team_app.command("init")
def team_init_cmd(
    remote: str = typer.Argument(..., help="Git URL or path of the team repository."),
    create: bool = typer.Option(
        False, "--create", help="Create a new bare repository at this path first."
    ),
    name: str = NAME,
    json_output: bool = JSON,
) -> None:
    """Connect to (or create) a team memory repository and clone it locally."""
    team = _team(name)
    _run(lambda: team.init(remote, create=create), json_output, _render_status)


def _render_status(result: dict[str, Any]) -> None:
    console.print(f"[bold]Team memory '{result['name']}'[/bold]")
    console.print(f"  remote   {escape(result['remote'])}")
    console.print(f"  nodes    {result['nodes']} reviewed")
    console.print(f"  inbox    {result['pending_proposals']} proposal(s) waiting")


@team_app.command("status")
def team_status_cmd(name: str = NAME, json_output: bool = JSON) -> None:
    """Show the team graph's remote, reviewed node count and waiting proposals."""
    team = _team(name)
    _run(team.status, json_output, _render_status)


@team_app.command("sync")
def team_sync_cmd(name: str = NAME, json_output: bool = JSON) -> None:
    """Pull the team's latest reviewed nodes (fast-forward only)."""
    team = _team(name)
    _run(team.sync, json_output, _render_status)


@team_app.command("propose")
def team_propose_cmd(
    node_ids: Annotated[list[str], typer.Argument(help="Personal memory node ids to share.")],
    message: str = typer.Option("", "--message", "-m", help="Why these nodes are useful."),
    name: str = NAME,
    json_output: bool = JSON,
) -> None:
    """Propose personal memory nodes for the team graph (a teammate must accept)."""
    from magent.config import user_memory_dir

    team = _team(name)
    personal = user_memory_dir(shared._require_user())

    def render(result: dict[str, Any]) -> None:
        console.print(
            f"[green]Proposed {len(result['nodes'])} node(s) as {result['id']}.[/green] "
            "A teammate can review it with `magent memory team inbox`."
        )

    _run(
        lambda: team.propose(node_ids, personal_dir=personal, message=message), json_output, render
    )


@team_app.command("inbox")
def team_inbox_cmd(name: str = NAME, json_output: bool = JSON) -> None:
    """List proposals waiting for review."""
    team = _team(name)

    def render(result: dict[str, Any]) -> None:
        if not result["proposals"]:
            console.print("[dim]No proposals are waiting for review.[/dim]")
            return
        table = Table("Proposal", "Author", "Title", "Nodes")
        for item in result["proposals"]:
            table.add_row(
                item["id"],
                item["author"],
                escape(item["title"]),
                ", ".join(change["path"].removeprefix("nodes/") for change in item["changes"]),
            )
        console.print(table)
        console.print("[dim]Review one with `magent memory team show <id>`.[/dim]")

    _run(team.inbox, json_output, render)


@team_app.command("show")
def team_show_cmd(proposal_id: str, name: str = NAME, json_output: bool = JSON) -> None:
    """Show a proposal's diff and automatic checks."""
    team = _team(name)

    def render(result: dict[str, Any]) -> None:
        console.print(f"[bold]{escape(result['title'])}[/bold]  by {result['author']}")
        checks = result["checks"]
        if checks["ok"]:
            console.print("[green]Checks passed.[/green]")
        for problem in checks["problems"]:
            console.print(f"[red]✗ {escape(problem)}[/red]")
        console.print(escape(result["diff"]) or "[dim](no node changes)[/dim]", highlight=False)

    _run(lambda: team.show(proposal_id), json_output, render)


@team_app.command("accept")
def team_accept_cmd(
    proposal_id: str,
    reason: str = typer.Option("", "--reason", help="Optional note for the review log."),
    allow_self_review: bool = typer.Option(
        False, "--allow-self-review", help="Accept your own proposal (one-person teams)."
    ),
    name: str = NAME,
    json_output: bool = JSON,
) -> None:
    """Merge a teammate's proposal into the team graph."""
    team = _team(name)
    _run(
        lambda: team.decide(
            proposal_id, decision="accept", reason=reason, allow_self_review=allow_self_review
        ),
        json_output,
        lambda result: console.print(f"[green]Accepted {result['id']}.[/green]"),
    )


@team_app.command("reject")
def team_reject_cmd(
    proposal_id: str,
    reason: str = typer.Option("", "--reason", help="Why; recorded in REVIEWS.jsonl."),
    name: str = NAME,
    json_output: bool = JSON,
) -> None:
    """Reject a proposal; nothing is merged and the decision is recorded."""
    team = _team(name)
    _run(
        lambda: team.decide(proposal_id, decision="reject", reason=reason),
        json_output,
        lambda result: console.print(f"Rejected {result['id']}."),
    )


@team_app.command("reviews")
def team_reviews_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum number of items to return."),
    name: str = NAME,
    json_output: bool = JSON,
) -> None:
    """Show recent review decisions from the team's REVIEWS.jsonl."""
    team = _team(name)

    def render(result: dict[str, Any]) -> None:
        table = Table("When", "Proposal", "Decision", "Author", "Reviewer", "Reason")
        for item in result["reviews"]:
            table.add_row(
                item["at"][:19],
                item["proposal"],
                item["decision"],
                item["author"],
                item["reviewer"],
                escape(item.get("reason", "")),
            )
        console.print(table)

    _run(lambda: {"ok": True, "reviews": team.reviews(limit)}, json_output, render)
