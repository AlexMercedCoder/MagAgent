"""Guided configuration and Open Agent Profile commands."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console


def register_profile_commands(profile_app: typer.Typer, *, store, console: Console) -> None:
    @profile_app.command("generate")
    def profile_generate_cmd(
        prompt: str = typer.Argument(..., help="Describe the specialist to create."),
        name: str = typer.Option("", "--name"),
        extends: str = typer.Option("", "--extends", help="Optional base profile."),
        scope: str = typer.Option(
            "project", "--scope", help="project, portable, user, or universal"
        ),
        project: str = typer.Option(".", "--project", "-p"),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Generate and validate without saving."
        ),
        yes: bool = typer.Option(
            False, "--yes", help="Save the validated draft without an interactive prompt."
        ),
    ) -> None:
        """Generate a reviewable OAP profile from a natural-language request."""
        from magent.agent_profiles.generation import (
            accept_generated_profile,
            generate_profile_proposal,
        )
        from magent.config import get_current_user, load_config

        username = get_current_user()
        if not username:
            console.print_json(
                data={"ok": False, "error": "Configure or select a MagAgent user first."}
            )
            raise typer.Exit(1)
        config = load_config(username)
        result = asyncio.run(
            generate_profile_proposal(
                prompt,
                project=project,
                config=config,
                name=name,
                extends=extends,
            )
        )
        if not result.get("ok"):
            console.print_json(data=result)
            raise typer.Exit(1)
        if dry_run:
            console.print_json(data=result)
            return
        document = result["document"]
        console.print_json(data={"document": document, "warnings": result.get("warnings", [])})
        approved = yes or typer.confirm(
            f"Save generated profile @{document['metadata']['name']} to {scope}?"
        )
        if not approved:
            console.print_json(data={**result, "ok": True, "saved": False, "cancelled": True})
            return
        saved = accept_generated_profile(result, scope=scope, project=project, config=config)
        console.print_json(
            data={
                **saved,
                "generation": {
                    "model": result.get("model"),
                    "prompt_digest": result.get("prompt_digest"),
                },
            }
        )
        if not saved.get("ok"):
            raise typer.Exit(1)

    @profile_app.command("wizard")
    def profile_wizard_cmd(
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Create a complete Open Agent Profile interactively."""
        from magent.agent_profiles.authoring import set_default_profile
        from magent.cli.profile_wizard import run_profile_wizard
        from magent.config import get_current_user, load_config

        username = get_current_user()
        if not username:
            console.print("[red]Configure or select a MagAgent user first.[/red]")
            raise typer.Exit(1)
        result = run_profile_wizard(
            username=username,
            config=load_config(username),
            store=store(),
            project=project,
            console=console,
        )
        if result.get("ok") and result.pop("make_default", False):
            result["default"] = set_default_profile(
                str(result["name"]), username=username, project=project
            )
        console.print_json(data=result)
        if not result.get("ok") and not result.get("cancelled"):
            raise typer.Exit(1)

    @profile_app.command("default")
    def profile_default_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show the active default Open Agent Profile."""
        from magent.agent_profiles.authoring import default_profile_status
        from magent.config import get_current_user

        result = default_profile_status(get_current_user(), project)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @profile_app.command("set-default")
    def profile_set_default_cmd(
        name: str = typer.Argument(..., help="Open Agent Profile name"),
        project: str = typer.Option(".", "--project", "-p"),
        global_scope: bool = typer.Option(
            False,
            "--global",
            help="Set the installation-wide fallback instead of the active user's default.",
        ),
    ) -> None:
        """Set the default profile used by REPL and one-shot sessions."""
        from magent.agent_profiles.authoring import set_default_profile
        from magent.config import get_current_user

        result = set_default_profile(
            name, username=get_current_user(), project=project, global_scope=global_scope
        )
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @profile_app.command("clear-default")
    def profile_clear_default_cmd(
        global_scope: bool = typer.Option(False, "--global"),
    ) -> None:
        """Clear the user override or reset the global default to magagent."""
        from magent.agent_profiles.authoring import clear_default_profile
        from magent.config import get_current_user

        result = clear_default_profile(username=get_current_user(), global_scope=global_scope)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
