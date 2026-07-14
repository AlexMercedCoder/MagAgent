"""Built-in documentation command registrations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register_docs_commands(
    docs_app: typer.Typer,
    *,
    known_command_names: Callable[[], list[str]],
) -> None:
    @docs_app.command("list")
    def docs_list_cmd() -> None:
        """List built-in documentation topics."""
        from magent.docs import list_topics

        table = Table("Topic", "Title")
        for topic in list_topics():
            table.add_row(topic.slug, topic.title)
        console.print(table)

    @docs_app.command("show")
    def docs_show_cmd(topic: str = typer.Argument(...)) -> None:
        """Show a built-in documentation topic."""
        from magent.docs import read_topic

        try:
            console.print(read_topic(topic))
        except KeyError:
            console.print(f"[red]Unknown docs topic: {topic}[/red]")
            raise typer.Exit(1) from None

    @docs_app.command("search")
    def docs_search_cmd(
        query: str = typer.Argument(...), limit: int = typer.Option(8, "--limit", "-n")
    ) -> None:
        """Search built-in MagAgent documentation."""
        from magent.docs import search_docs

        results = search_docs(query, limit=limit)
        table = Table("Topic", "Score", "Snippet")
        for item in results:
            table.add_row(item["slug"], str(item["score"]), item["snippet"])
        console.print(table)

    @docs_app.command("doctor")
    def docs_doctor_cmd() -> None:
        """Check built-in docs coverage."""
        from magent.docs import docs_doctor

        console.print_json(data=docs_doctor(known_command_names()))

    @docs_app.command("generate-reference")
    def docs_generate_reference_cmd(
        out: str | None = typer.Option(None, "--out", "-o"),
        check: bool = typer.Option(
            False, "--check", help="Fail if the generated reference differs from --out."
        ),
    ) -> None:
        """Generate command reference Markdown from the live CLI tree."""
        from magent.docs import render_command_reference

        text = render_command_reference(known_command_names())
        target = Path(out or "src/magent/docs/command-reference.md")
        if check:
            if not target.exists():
                console.print(f"[red]Command reference is missing: {target}[/red]")
                raise typer.Exit(1)
            if target.read_text(encoding="utf-8", errors="replace") != text:
                console.print(f"[red]Command reference is stale: {target}[/red]")
                console.print(f"[dim]Run: magent docs generate-reference --out {target}[/dim]")
                raise typer.Exit(1)
            console.print(f"[green]✓ Command reference is current: {target}[/green]")
        elif out:
            target.write_text(text, encoding="utf-8")
            console.print(f"[green]✓ Wrote {target}[/green]")
        else:
            console.print(text)

    @docs_app.command("generate-providers")
    def docs_generate_providers_cmd(out: str | None = typer.Option(None, "--out", "-o")) -> None:
        """Generate provider reference Markdown from the provider catalog."""
        from magent.docs import render_provider_reference

        text = render_provider_reference()
        target = Path(out or "src/magent/docs/providers.md")
        target.write_text(text, encoding="utf-8")
        console.print(f"[green]✓ Wrote {target}[/green]")

    @docs_app.command("generate-config")
    def docs_generate_config_cmd(out: str | None = typer.Option(None, "--out", "-o")) -> None:
        """Generate config reference Markdown from packaged defaults."""
        from magent.docs import render_config_reference

        text = render_config_reference()
        target = Path(out or "src/magent/docs/config-reference.md")
        target.write_text(text, encoding="utf-8")
        console.print(f"[green]✓ Wrote {target}[/green]")
