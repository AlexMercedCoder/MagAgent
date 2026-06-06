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
