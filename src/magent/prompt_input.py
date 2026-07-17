"""Interactive prompt input helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.prompt import Prompt

from magent.config import CONFIG_DIR


def read_user_prompt(username: str) -> str:
    """Read one REPL prompt with optional Shift+Enter newline support."""
    if not sys.stdin.isatty():
        return Prompt.ask(f"[bold cyan]({username})[/bold cyan] [bold]>[/bold]")
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return Prompt.ask(f"[bold cyan]({username})[/bold cyan] [bold]>[/bold]")

    bindings = KeyBindings()

    def insert_newline(event) -> None:
        event.current_buffer.insert_text("\n")

    _try_bind(bindings, ("s-enter",), insert_newline)
    _try_bind(bindings, ("c-j",), insert_newline)

    session = PromptSession(key_bindings=bindings, history=FileHistory(str(_history_path(username, "prompt"))))
    text = session.prompt(f"({username}) > ")
    if text.strip() == "/editor":
        return _read_editor_prompt(username)
    return text


def read_multiline_prompt(username: str) -> str:
    """Read a formatted multiline prompt; Enter inserts newlines."""
    if not sys.stdin.isatty():
        return Prompt.ask(f"[bold cyan]({username})[/bold cyan] [bold]compose>[/bold]")
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
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
        history=FileHistory(str(_history_path(username, "compose"))),
        multiline=True,
        bottom_toolbar="Enter newline • Esc+Enter/Ctrl+D submit • type /editor to open $EDITOR • Ctrl+C cancel",
    )
    text = session.prompt(f"({username}) compose> ")
    if text.strip() == "/editor":
        return _read_editor_prompt(username)
    return text


def _rich_multiline_fallback(username: str) -> str:
    lines: list[str] = []
    print(f"({username}) compose> Enter your prompt. Submit with /send, or type /editor to open $EDITOR.")
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "/editor" and not lines:
            return _read_editor_prompt(username)
        if line.strip() == "/send":
            break
        lines.append(line)
    return "\n".join(lines)


def _try_bind(bindings, keys: tuple[str, ...], handler) -> None:
    try:
        bindings.add(*keys)(handler)
    except ValueError:
        return


def _history_path(username: str, mode: str) -> Path:
    path = CONFIG_DIR / "prompt-history" / f"{username}-{mode}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_editor_prompt(username: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    with tempfile.NamedTemporaryFile("w+", suffix=f"-{username}-magent-prompt.md", encoding="utf-8") as handle:
        handle.write("# Write your MagAgent prompt below. Lines starting with # are ignored.\n\n")
        handle.flush()
        try:
            subprocess.run([editor, handle.name], check=False)
        except FileNotFoundError:
            return ""
        handle.seek(0)
        lines = [
            line.rstrip()
            for line in handle.read().splitlines()
            if not line.lstrip().startswith("#")
        ]
    return "\n".join(lines).strip()
