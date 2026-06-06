from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console

from magent import tui


def test_context_line_compacts_home_path() -> None:
    line = tui.context_line(
        "alex",
        "Ollama",
        str(Path.home() / "projects" / "magagent"),
        "ask",
        model="llama",
        git_branch="main",
    )

    assert "alex" in line
    assert "Ollama" in line
    assert "llama" in line
    assert "main" in line
    assert "~/projects/magagent" in line


def test_print_banner_renders_compact_session_context(monkeypatch) -> None:
    captured = Console(record=True, width=60, color_system=None)
    monkeypatch.setattr(tui, "console", captured)

    tui.print_banner("alex", "Ollama", "/repo", "ask", model="llama")

    output = captured.export_text()
    assert "MagAgent" in output
    assert "alex" in output
    assert "Ollama" in output
    assert "/repo" in output


def test_print_response_uses_agent_panel(monkeypatch) -> None:
    captured = Console(record=True, width=90, color_system=None)
    monkeypatch.setattr(tui, "console", captured)

    tui.print_response("## Done\n\nAll set.")

    output = captured.export_text()
    assert "MagAgent" in output
    assert "Done" in output
    assert "All set." in output


def test_print_status_and_error(monkeypatch) -> None:
    captured = Console(record=True, width=90, color_system=None)
    monkeypatch.setattr(tui, "console", captured)

    tui.print_status("checkpoint saved", level="success", detail="abc123")
    tui.print_error("command failed", detail="pytest")

    output = captured.export_text()
    assert "ok checkpoint saved" in output
    assert "abc123" in output
    assert "error command failed" in output
    assert "pytest" in output


def test_streaming_response_does_not_duplicate_by_default(monkeypatch) -> None:
    captured = Console(record=True, width=90, color_system=None)
    monkeypatch.setattr(tui, "console", captured)

    async def chunks():
        yield "hello"
        yield " world"

    loop = asyncio.new_event_loop()
    try:
        tui.print_streaming_response(chunks(), loop)
    finally:
        loop.close()

    output = captured.export_text()
    assert output.count("hello world") == 1
    assert "Rendered" not in output


def test_streaming_response_can_render_final_markdown(monkeypatch) -> None:
    captured = Console(record=True, width=90, color_system=None)
    monkeypatch.setattr(tui, "console", captured)

    async def chunks():
        yield "**done**"

    loop = asyncio.new_event_loop()
    try:
        tui.print_streaming_response(chunks(), loop, render_final_markdown=True)
    finally:
        loop.close()

    output = captured.export_text()
    assert "**done**" in output
    assert "Rendered" in output
