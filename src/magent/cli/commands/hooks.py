"""Hook command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_hook_commands(hook_app: typer.Typer) -> None:
    @hook_app.command("init")
    def hook_init_cmd(project: str = typer.Option(".", "--project", "-p"), force: bool = typer.Option(False, "--force")) -> None:
        """Create `.magent/hooks.toml`."""
        from magent.hooks import init_hooks

        console.print_json(data=init_hooks(project, force=force))

    @hook_app.command("list")
    def hook_list_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """List configured project hooks."""
        from magent.hooks import load_hooks

        console.print_json(data={"ok": True, "hooks": load_hooks(project)})

    @hook_app.command("run")
    def hook_run_cmd(event: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")) -> None:
        """Run hooks for an event with a small test payload."""
        from magent.hooks import run_hooks

        console.print_json(data={"ok": True, "results": run_hooks(project, event, {"manual": True})})
