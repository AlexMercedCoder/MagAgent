"""TUI helpers: banner, response rendering, streaming, and status output."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()

LOGO = "MagAgent"
MAGPIE_PET = "\n".join(
    [
        "[bold white]  ,_[/bold white]",
        "[bold cyan]<(o )___[/bold cyan]",
        "[dim]  (___/[/dim]",
    ]
)


@dataclass(frozen=True)
class TuiTheme:
    """Named styles used by MagAgent's terminal UI."""

    accent: str = "bold magenta"
    border: str = "magenta"
    success: str = "green"
    warning: str = "yellow"
    danger: str = "red"
    muted: str = "dim"
    user: str = "bold cyan"
    provider: str = "bold white"
    mode: str = "bold yellow"
    path: str = "dim"


THEME = TuiTheme()


def context_line(
    username: str,
    provider: str,
    cwd: str,
    mode: str,
    *,
    model: str | None = None,
    git_branch: str | None = None,
) -> str:
    """Return a compact one-line session context summary."""
    parts = [
        f"[{THEME.muted}]user[/{THEME.muted}] [{THEME.user}]{username}[/{THEME.user}]",
        f"[{THEME.muted}]provider[/{THEME.muted}] [{THEME.provider}]{provider}[/{THEME.provider}]",
    ]
    if model:
        parts.append(f"[{THEME.muted}]model[/{THEME.muted}] [{THEME.provider}]{model}[/{THEME.provider}]")
    parts.append(f"[{THEME.muted}]mode[/{THEME.muted}] [{THEME.mode}]{mode}[/{THEME.mode}]")
    if git_branch:
        parts.append(f"[{THEME.muted}]git[/{THEME.muted}] [bold]{git_branch}[/bold]")
    parts.append(f"[{THEME.muted}]cwd[/{THEME.muted}] [{THEME.path}]{_compact_path(cwd)}[/{THEME.path}]")
    return "  ".join(parts)


def print_banner(
    username: str,
    provider: str,
    cwd: str,
    mode: str,
    *,
    version: str = "",
    model: str | None = None,
    git_branch: str | None = None,
) -> None:
    """Print a compact startup banner that adapts to terminal width."""
    title = f"{LOGO} {version}".strip()
    if console.width < 72:
        console.print(
            Panel(
                context_line(
                    username,
                    provider,
                    cwd,
                    mode,
                    model=model,
                    git_branch=git_branch,
                ),
                title=f"[{THEME.accent}]{title}[/{THEME.accent}]",
                border_style=THEME.border,
                expand=True,
            )
        )
        return

    table = Table.grid(expand=True)
    table.add_column(width=12)
    table.add_column(ratio=1)
    table.add_column(ratio=4)
    table.add_row(
        MAGPIE_PET,
        f"[{THEME.accent}]{title}[/{THEME.accent}]",
        context_line(username, provider, cwd, mode, model=model, git_branch=git_branch),
    )
    console.print(Panel(table, border_style=THEME.border, box=box.ROUNDED, padding=(1, 2)))


def print_response(text: str) -> None:
    """Render agent response as Rich Markdown."""
    try:
        console.print(Panel(Markdown(text), title="MagAgent", border_style=THEME.border, box=box.ROUNDED))
    except Exception:
        console.print(text)
    console.print()


def print_status(message: str, *, level: str = "info", detail: str | None = None) -> None:
    """Render a compact operational status line."""
    styles = {
        "success": THEME.success,
        "warning": THEME.warning,
        "error": THEME.danger,
        "info": THEME.muted,
    }
    labels = {
        "success": "ok",
        "warning": "warn",
        "error": "error",
        "info": "info",
    }
    style = styles.get(level, THEME.muted)
    label = labels.get(level, "info")
    suffix = f" [dim]· {detail}[/dim]" if detail else ""
    console.print(f"[{style}]{label}[/{style}] {message}{suffix}")


def print_error(message: str, *, detail: str | None = None) -> None:
    """Render a compact error status line."""
    print_status(message, level="error", detail=detail)


def print_streaming_response(
    async_gen: AsyncIterator[str],
    loop: asyncio.AbstractEventLoop,
    *,
    render_final_markdown: bool = False,
) -> None:
    """
    Consume a streaming async generator and render output live.
    By default this does not re-render the final Markdown, avoiding duplicated
    answers in interactive sessions.
    """
    accumulated = ""

    async def _consume():
        nonlocal accumulated
        async for chunk in async_gen:
            accumulated += chunk
            console.print(chunk, end="", markup=False)

    task = loop.create_task(_consume())
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
        with suppress(Exception):
            loop.run_until_complete(task)
        raise
    console.print()
    if render_final_markdown and accumulated.strip():
        console.print()
        with suppress(Exception):
            console.print(Panel(Markdown(accumulated), title="Rendered", border_style=THEME.border, box=box.ROUNDED))
    console.print()


def _compact_path(path: str) -> str:
    expanded = str(Path(path).expanduser())
    home = str(Path.home())
    if expanded == home:
        return "~"
    if expanded.startswith(home + "/"):
        return "~/" + expanded[len(home) + 1 :]
    return expanded
