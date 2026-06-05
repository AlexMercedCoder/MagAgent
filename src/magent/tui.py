"""TUI helpers: banner, response rendering."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

BANNER = r"""
 __  __            _    _                    _   
|  \/  |          / \  | |   __ _  ___ _ __ | |_ 
| |\/| |         / _ \ | |  / _` |/ _ \ '_ \| __|
| |  | |  _     / ___ \| |_| (_| |  __/ | | | |_ 
|_|  |_| (_)   /_/   \_\_____\__, |\___|_| |_|\__|
                               |___/               
"""


def print_banner(username: str, provider: str, cwd: str, mode: str) -> None:
    console.print(
        Panel(
            f"[bold magenta]{BANNER}[/bold magenta]"
            f"[dim]User:[/dim] [bold cyan]{username}[/bold cyan]  "
            f"[dim]Provider:[/dim] [bold]{provider}[/bold]  "
            f"[dim]Mode:[/dim] [bold yellow]{mode}[/bold yellow]  "
            f"[dim]CWD:[/dim] [dim]{cwd}[/dim]",
            border_style="magenta",
            expand=True,
        )
    )


def print_response(text: str) -> None:
    """Render agent response as Rich Markdown."""
    try:
        console.print(Markdown(text))
    except Exception:
        console.print(text)
    console.print()
