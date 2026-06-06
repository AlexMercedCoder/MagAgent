"""Plugin pack command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_plugin_commands(plugin_app: typer.Typer) -> None:
    @plugin_app.command("list")
    def plugin_list_cmd() -> None:
        """List installed extension packs."""
        from magent.plugins import list_plugins

        console.print_json(data=list_plugins())

    @plugin_app.command("install")
    def plugin_install_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Install a local plugin pack directory."""
        from magent.plugins import install_plugin

        result = install_plugin(source, name=name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @plugin_app.command("enable")
    def plugin_enable_cmd(name: str = typer.Argument(...)) -> None:
        """Enable an installed plugin pack."""
        from magent.plugins import set_plugin_enabled

        console.print_json(data=set_plugin_enabled(name, True))

    @plugin_app.command("disable")
    def plugin_disable_cmd(name: str = typer.Argument(...)) -> None:
        """Disable an installed plugin pack."""
        from magent.plugins import set_plugin_enabled

        console.print_json(data=set_plugin_enabled(name, False))
