"""Browser automation command registrations."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console

console = Console()


def register_browser_commands(browser_app: typer.Typer, webmcp_app: typer.Typer) -> None:
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

    def settings() -> tuple[list[str], bool]:
        from magent.browser import normalize_webmcp_origins
        from magent.config import load_global_config

        section = load_global_config().get("webmcp", {})
        return list(normalize_webmcp_origins(section.get("origins"))), bool(
            section.get("headless", False)
        )

    @webmcp_app.command("status")
    def webmcp_status_cmd() -> None:
        """Report dependency, browser-profile, and allowlisted-origin readiness."""
        from magent.browser import _webmcp_profile_dir

        origins, headless = settings()
        package_installed = False
        browser_path = ""
        try:
            from pathlib import Path

            from playwright.sync_api import sync_playwright

            package_installed = True
            with sync_playwright() as runtime:
                browser_path = runtime.chromium.executable_path
            installed = Path(browser_path).is_file()
        except Exception:
            installed = False
        console.print_json(
            data={
                "ok": installed,
                "schema_version": "webmcp.runtime.v1",
                "available": installed,
                "browser": {
                    "package_installed": package_installed,
                    "installed": installed,
                    "executable": browser_path,
                    "headless": headless,
                },
                "origins": [
                    {
                        "origin": origin,
                        "enabled": True,
                        "policy": "allowlisted",
                        "browser_profile": str(_webmcp_profile_dir(origin)),
                    }
                    for origin in origins
                ],
            }
        )

    @webmcp_app.command("origins")
    def webmcp_origins_cmd() -> None:
        """List configured exact HTTPS origins."""
        origins, _ = settings()
        console.print_json(data={"ok": True, "origins": origins})

    @webmcp_app.command("origin-add")
    def webmcp_origin_add_cmd(origin: str = typer.Argument(...)) -> None:
        """Add one exact HTTPS origin to the reviewed allowlist."""
        from magent.browser import normalize_webmcp_origins, require_webmcp_url
        from magent.config import load_global_config, save_global_config

        normalized = normalize_webmcp_origins([origin])
        candidate = normalized[0]
        require_webmcp_url(candidate + "/", normalized)
        cfg = load_global_config()
        current = list(normalize_webmcp_origins(cfg.get("webmcp", {}).get("origins")))
        cfg.setdefault("webmcp", {})["origins"] = list(dict.fromkeys([*current, candidate]))
        save_global_config(cfg)
        console.print_json(
            data={"ok": True, "origin": candidate, "origins": cfg["webmcp"]["origins"]}
        )

    @webmcp_app.command("origin-remove")
    def webmcp_origin_remove_cmd(origin: str = typer.Argument(...)) -> None:
        """Remove an origin without deleting its browser profile."""
        from magent.browser import normalize_webmcp_origins
        from magent.config import load_global_config, save_global_config

        cfg = load_global_config()
        current = list(normalize_webmcp_origins(cfg.get("webmcp", {}).get("origins")))
        requested = str(origin).rstrip("/").lower()
        remaining = [item for item in current if item.lower() != requested]
        if not remaining:
            raise typer.BadParameter("At least one WebMCP origin must remain configured.")
        cfg.setdefault("webmcp", {})["origins"] = remaining
        save_global_config(cfg)
        console.print_json(data={"ok": True, "origins": remaining})

    @webmcp_app.command("open")
    def webmcp_open_cmd(
        url: str = typer.Argument("https://alexmerced.app"), wait_ms: int = 750
    ) -> None:
        """Open an allowlisted page and return its authoritative live tool registry."""
        from magent.browser import webmcp_inspect

        origins, headless = settings()
        console.print_json(
            data=asyncio.run(
                webmcp_inspect(url, wait_ms=wait_ms, allowed_origins=origins, headless=headless)
            )
        )

    @webmcp_app.command("call")
    def webmcp_call_cmd(
        name: str = typer.Argument(...),
        url: str = typer.Option("https://alexmerced.app", "--url"),
        arguments: str = typer.Option("{}", "--arguments"),
        registry_revision: str = typer.Option("", "--registry-revision"),
        yes: bool = typer.Option(False, "--yes", help="Approve this direct invocation once."),
    ) -> None:
        """Call an exact discovered tool; agent sessions still provide approval enforcement."""
        from magent.browser import webmcp_invoke

        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise typer.BadParameter(f"Arguments must be a JSON object: {error}") from error
        if not isinstance(payload, dict):
            raise typer.BadParameter("Arguments must be a JSON object.")
        if not yes:
            raise typer.BadParameter(
                "Direct WebMCP calls require --yes. Agent sessions use normal runtime approvals."
            )
        origins, headless = settings()
        console.print_json(
            data=asyncio.run(
                webmcp_invoke(
                    url,
                    name,
                    payload,
                    allowed_origins=origins,
                    expected_revision=registry_revision,
                    headless=headless,
                )
            )
        )
