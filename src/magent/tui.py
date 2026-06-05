"""TUI helpers: banner, response rendering, streaming."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

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


def print_streaming_response(
    async_gen: AsyncIterator[str],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Consume a streaming async generator and render output live.
    Accumulates tokens, then re-renders as Markdown when done.
    """
    accumulated = ""

    # Stream tokens to terminal directly (no Live panel — simpler, no flicker)
    async def _consume():
        nonlocal accumulated
        async for chunk in async_gen:
            accumulated += chunk
            # Print raw chunk immediately for responsiveness
            console.print(chunk, end="", markup=False)

    loop.run_until_complete(_consume())

    # After streaming is done, print a newline then re-render as Markdown
    console.print()  # newline after raw stream
    console.print()
    try:
        # Re-render final output as formatted Markdown
        console.rule(style="dim")
        console.print(Markdown(accumulated))
    except Exception:
        pass  # already printed raw above
    console.print()
