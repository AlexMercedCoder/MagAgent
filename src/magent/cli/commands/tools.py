"""Tool capability and backend command registrations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console
from rich.table import Table


def register_tool_commands(
    tools_app: typer.Typer,
    *,
    store: Callable[[], Any],
    load_active_config: Callable[[], Any],
    console: Console,
) -> None:
    @tools_app.command("list")
    def tools_list_cmd() -> None:
        """List tool capability packs and enabled state."""
        from magent.tool_packs import list_packs

        console.print_json(data={"ok": True, "packs": list_packs(store())})

    @tools_app.command("explain")
    def tools_explain_cmd(pack: str = typer.Argument(...)) -> None:
        """Explain a tool capability pack."""
        from magent.tool_packs import explain_pack

        result = explain_pack(pack, store())
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    def set_enabled(pack: str, enabled: bool) -> None:
        from magent.tool_packs import set_pack_enabled

        result = set_pack_enabled(store(), pack, enabled)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @tools_app.command("enable")
    def tools_enable_cmd(pack: str = typer.Argument(...)) -> None:
        """Enable a tool capability pack."""
        set_enabled(pack, True)

    @tools_app.command("disable")
    def tools_disable_cmd(pack: str = typer.Argument(...)) -> None:
        """Disable a tool capability pack."""
        set_enabled(pack, False)

    @tools_app.command("gateway")
    def tools_gateway_cmd() -> None:
        """Show local, subscription, and MCP tool backend readiness."""
        from magent.tool_gateway import gateway_status

        data = gateway_status(load_active_config())
        table = Table("Backend", "Enabled", "Credential", "Description")
        for item in data.get("backends", []):
            table.add_row(
                item.get("id", ""),
                "yes" if item.get("enabled") else "no",
                item.get("credential") or "-",
                item.get("description", "")[:90],
            )
        console.print(table)

    @tools_app.command("backend")
    def tools_backend_cmd(name: str = typer.Argument(...)) -> None:
        """Explain one tool backend/gateway surface."""
        from magent.tool_gateway import explain_backend

        result = explain_backend(name)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @tools_app.command("doctor")
    def tools_doctor_cmd() -> None:
        """Report optional capability readiness and install commands."""
        from magent.capability_readiness import readiness_report

        console.print_json(data=readiness_report())
