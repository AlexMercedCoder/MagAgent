"""Permission profile UX command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_permission_commands(permission_app: typer.Typer) -> None:
    @permission_app.command("status")
    def permission_status_cmd() -> None:
        """Show the active user's permission profile."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_status

        console.print_json(data=permission_status(require_user()))

    @permission_app.command("explain")
    def permission_explain_cmd(mode: str = typer.Argument(...)) -> None:
        """Explain a permission mode."""
        from magent.permission_ux import permission_explain

        result = permission_explain(mode)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @permission_app.command("set")
    def permission_set_cmd(
        mode: str = typer.Argument(...),
        yes: bool = typer.Option(False, "--yes", "-y", help="Required for yolo mode."),
    ) -> None:
        """Set the active user's permission mode."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_set

        if mode.strip().lower() == "yolo" and not yes:
            console.print("[red]yolo mode requires --yes.[/red]")
            raise typer.Exit(1)
        result = permission_set(require_user(), mode)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @permission_app.command("propose")
    def permission_propose_cmd(text: str = typer.Argument(...)) -> None:
        """Parse a natural-language permission request into a suggested action."""
        from magent.permission_ux import permission_propose

        console.print_json(data=permission_propose(text))

    @permission_app.command("trust-list")
    def permission_trust_list_cmd() -> None:
        """Show shell patterns saved by session/always approvals."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_trust_list

        console.print_json(data=permission_trust_list(require_user()))

    @permission_app.command("trust-clear")
    def permission_trust_clear_cmd(
        pattern: str = typer.Argument("", help="Exact trusted pattern to remove; omit to clear all."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Required when clearing all trusted shell patterns."),
    ) -> None:
        """Remove saved trusted shell approval patterns."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_trust_clear

        if not pattern and not yes:
            console.print("[red]Clearing all trusted shell patterns requires --yes.[/red]")
            raise typer.Exit(1)
        console.print_json(data=permission_trust_clear(require_user(), pattern))
