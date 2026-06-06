"""Config safety command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_config_commands(config_app: typer.Typer) -> None:
    @config_app.command("show")
    def config_show_cmd() -> None:
        """Show global/current-user config file paths and text."""
        from magent.config_safety import show_config

        console.print_json(data=show_config())

    @config_app.command("backup")
    def config_backup_cmd() -> None:
        """Create a timestamped backup of global/current-user config."""
        from magent.config_safety import backup_config

        console.print_json(data=backup_config())

    @config_app.command("list-backups")
    def config_list_backups_cmd() -> None:
        """List config backups."""
        from magent.config_safety import list_config_backups

        console.print_json(data=list_config_backups())

    @config_app.command("diff")
    def config_diff_cmd(backup_id: str | None = typer.Argument(None)) -> None:
        """Diff current config against a backup, defaulting to the latest backup."""
        from magent.config_safety import diff_config

        result = diff_config(backup_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @config_app.command("restore")
    def config_restore_cmd(backup_id: str = typer.Argument(...)) -> None:
        """Restore global/current-user config from a backup."""
        from magent.config_safety import restore_config

        result = restore_config(backup_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @config_app.command("propose")
    def config_propose_cmd(text: str = typer.Argument(...)) -> None:
        """Create a safe config proposal from a natural-language request."""
        from magent.cli.command_context import require_user, store
        from magent.config_proposals import propose_config_change

        username = require_user()
        result = propose_config_change(store(), text, username)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @config_app.command("proposals")
    def config_proposals_cmd(status: str = typer.Option("pending", "--status")) -> None:
        """List config proposals."""
        from magent.cli.command_context import store
        from magent.config_proposals import list_config_proposals

        console.print_json(data=list_config_proposals(store(), status=status))

    @config_app.command("apply")
    def config_apply_cmd(
        proposal_id: str = typer.Argument(...),
        yes: bool = typer.Option(False, "--yes", "-y", help="Apply high-risk proposals without an interactive prompt."),
    ) -> None:
        """Apply a pending config proposal after backing up config files."""
        from magent.cli.command_context import require_user, store
        from magent.config_proposals import apply_config_proposal, list_config_proposals

        username = require_user()
        workbench = store()
        proposal = next(
            (
                item
                for item in list_config_proposals(workbench, status="pending").get("proposals", [])
                if item.get("id") == proposal_id
            ),
            None,
        )
        if proposal and proposal.get("requires_typed_confirm") and not yes:
            console.print("[red]High-risk proposal requires --yes.[/red]")
            raise typer.Exit(1)
        result = apply_config_proposal(workbench, proposal_id, username)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @config_app.command("discard")
    def config_discard_cmd(proposal_id: str = typer.Argument(...)) -> None:
        """Discard a pending config proposal."""
        from magent.cli.command_context import store
        from magent.config_proposals import discard_config_proposal

        result = discard_config_proposal(store(), proposal_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
