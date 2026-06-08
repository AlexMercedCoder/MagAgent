"""Interactive prompt input helpers."""

from __future__ import annotations

import sys

from rich.prompt import Prompt


def read_user_prompt(username: str) -> str:
    """Read one REPL prompt with optional Shift+Enter newline support."""
    if not sys.stdin.isatty():
        return Prompt.ask(f"[bold cyan]({username})[/bold cyan] [bold]>[/bold]")
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return Prompt.ask(f"[bold cyan]({username})[/bold cyan] [bold]>[/bold]")

    bindings = KeyBindings()

    def insert_newline(event) -> None:
        event.current_buffer.insert_text("\n")

    _try_bind(bindings, ("s-enter",), insert_newline)
    _try_bind(bindings, ("c-j",), insert_newline)

    session = PromptSession(key_bindings=bindings)
    return session.prompt(f"({username}) > ")


def read_multiline_prompt(username: str) -> str:
    """Read a formatted multiline prompt; Enter inserts newlines."""
    if not sys.stdin.isatty():
        return Prompt.ask(f"[bold cyan]({username})[/bold cyan] [bold]compose>[/bold]")
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return _rich_multiline_fallback(username)

    bindings = KeyBindings()

    def submit(event) -> None:
        event.current_buffer.validate_and_handle()

    _try_bind(bindings, ("escape", "enter"), submit)
    _try_bind(bindings, ("c-d",), submit)

    session = PromptSession(
        key_bindings=bindings,
        multiline=True,
        bottom_toolbar="Enter newline • Esc+Enter or Ctrl+D submit • Ctrl+C cancel",
    )
    return session.prompt(f"({username}) compose> ")


def _rich_multiline_fallback(username: str) -> str:
    lines: list[str] = []
    print(f"({username}) compose> Enter your prompt. Submit with a line containing only /send.")
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "/send":
            break
        lines.append(line)
    return "\n".join(lines)


def _try_bind(bindings, keys: tuple[str, ...], handler) -> None:
    try:
        bindings.add(*keys)(handler)
    except ValueError:
        return
