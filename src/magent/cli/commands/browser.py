"""Browser automation command registrations."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

console = Console()


def register_browser_commands(browser_app: typer.Typer) -> None:
    @browser_app.command("snapshot")
    def browser_snapshot_cmd(
        url: str = typer.Argument(...),
        wait_ms: int = typer.Option(500, "--wait-ms"),
    ) -> None:
        """Capture title and text from a page using Playwright."""
        from magent.browser import browser_snapshot

        console.print_json(data=asyncio.run(browser_snapshot(url, wait_ms=wait_ms)))

    @browser_app.command("screenshot")
    def browser_screenshot_cmd(
        url: str = typer.Argument(...),
        out: str = typer.Option("magent-browser.png", "--out", "-o"),
        wait_ms: int = typer.Option(500, "--wait-ms"),
    ) -> None:
        """Capture a page screenshot using Playwright."""
        from magent.browser import browser_screenshot

        console.print_json(data=asyncio.run(browser_screenshot(url, out, wait_ms=wait_ms)))
