"""Config safety command registrations."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def register_config_commands(config_app: typer.Typer) -> None:
    @config_app.command("ux")
    def config_ux_cmd(user: str | None = typer.Option(None, "--user", "-u")) -> None:
        """Show a friendly control-center summary for common configuration UX."""
        from magent.config import get_current_user, load_config

        username = user or get_current_user()
        config = load_config(username)
        console.print(Panel.fit("[bold]MagAgent Config[/bold]", title="Control Center"))
        table = Table("Area", "Current", "Try")
        table.add_row("Provider", f"{config.default_provider}/{config.default_model}", "magent provider wizard")
        table.add_row(
            "Model roles",
            ", ".join(f"{role}:{value or '-'}" for role, value in config.model_roles.items()),
            "magent model wizard",
        )
        table.add_row("Permissions", config.permission_mode, "magent permission set balanced")
        table.add_row("Memory", f"write every {config.write_every_n_turns} turns", "magent memory configure")
        table.add_row(
            "Subagents",
            f"max {config.max_subagents}, parallel {config.max_parallel_subagents}",
            "magent subagent wizard",
        )
        table.add_row("Context", "audit active prompt load", "magent context audit")
        table.add_row("Jobs", "background daemon queue", "magent jobs")
        console.print(table)

    @config_app.command("get")
    def config_get_cmd(
        user: str | None = typer.Option(None, "--user", "-u"),
        raw: bool = typer.Option(False, "--raw", help="Include redacted raw TOML text."),
    ) -> None:
        """Return machine-readable redacted config for desktop integrations."""
        from magent.desktop_api import config_get

        console.print_json(data=config_get(user, include_raw=raw))

    @config_app.command("schema")
    def config_schema_cmd(user: str | None = typer.Option(None, "--user", "-u")) -> None:
        """Return guided config field metadata for desktop integrations."""
        from magent.desktop_api import config_schema

        console.print_json(data=config_schema(user))

    @config_app.command("set")
    def config_set_cmd(
        path: str = typer.Argument(..., help="Dot-path config key to set."),
        value: str = typer.Argument(..., help="JSON value or string value."),
        scope: str = typer.Option("global", "--scope", help="global or user"),
        user: str | None = typer.Option(None, "--user", "-u"),
    ) -> None:
        """Set a machine-readable config value without hand-editing TOML."""
        from magent.desktop_api import config_set, parse_json_value

        result = config_set(path, parse_json_value(value), username=user, scope=scope)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

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
