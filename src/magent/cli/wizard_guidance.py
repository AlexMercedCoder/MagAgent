"""Consistent, compact guidance for interactive CLI wizards."""

from __future__ import annotations

from collections.abc import Iterable

from rich.console import Console
from rich.table import Table


def explain_options(
    console: Console,
    title: str,
    options: Iterable[tuple[str, str]],
    *,
    note: str = "",
) -> None:
    """Render a small choice table immediately before its prompt."""
    table = Table(title=title, show_header=False, box=None, padding=(0, 1))
    table.add_column("Option", style="bold cyan", no_wrap=True)
    table.add_column("Meaning")
    for name, meaning in options:
        table.add_row(name, meaning)
    console.print(table)
    if note:
        console.print(f"[dim]{note}[/dim]")


def explain_field(console: Console, label: str, meaning: str) -> None:
    """Explain a free-form field without introducing another prompt."""
    console.print(f"[bold]{label}[/bold] [dim]{meaning}[/dim]")
