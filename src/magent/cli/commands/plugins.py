"""Plugin pack command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_plugin_commands(plugin_app: typer.Typer) -> None:
    import_app = typer.Typer(help="Import plugins from other agent ecosystems", name="import")
    mcp_app = typer.Typer(help="Import and apply MCP plugin packs", name="mcp")
    plugin_app.add_typer(import_app, name="import")
    plugin_app.add_typer(mcp_app, name="mcp")

    @plugin_app.command("list")
    def plugin_list_cmd(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
        """List installed extension packs."""
        from magent.plugins import list_plugins

        data = list_plugins()
        if json_output:
            console.print_json(data=data)
            return
        for item in data.get("plugins", []):
            state = "enabled" if item.get("enabled") else "disabled"
            console.print(f"{item.get('name', '')}\t{state}")

    @plugin_app.command("install")
    def plugin_install_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Install a local plugin pack directory."""
        from magent.plugins import install_plugin

        result = install_plugin(source, name=name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @plugin_app.command("enable")
    def plugin_enable_cmd(name: str = typer.Argument(...)) -> None:
        """Enable an installed plugin pack."""
        from magent.plugins import set_plugin_enabled

        console.print_json(data=set_plugin_enabled(name, True))

    @plugin_app.command("disable")
    def plugin_disable_cmd(name: str = typer.Argument(...)) -> None:
        """Disable an installed plugin pack."""
        from magent.plugins import set_plugin_enabled

        console.print_json(data=set_plugin_enabled(name, False))

    @plugin_app.command("metadata")
    def plugin_metadata_cmd(path: str = typer.Argument(...)) -> None:
        """Normalize plugin metadata from native or foreign manifests."""
        from magent.plugins import normalize_plugin_metadata

        console.print_json(data=normalize_plugin_metadata(path))

    @mcp_app.command("import")
    def plugin_mcp_import_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
        apply: bool = typer.Option(False, "--apply", help="Also write servers into config.toml."),
    ) -> None:
        """Import an MCP server config file or directory as a plugin pack."""
        from magent.plugins import import_mcp_plugin

        result = import_mcp_plugin(source, name=name, force=force, apply=apply)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @mcp_app.command("apply")
    def plugin_mcp_apply_cmd(
        name: str = typer.Argument(...),
        force: bool = typer.Option(False, "--force", help="Overwrite existing server names."),
    ) -> None:
        """Apply an installed plugin's MCP servers into config.toml."""
        from magent.plugins import apply_plugin_mcp

        result = apply_plugin_mcp(name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @import_app.command("opencode")
    def plugin_import_opencode_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Import OpenCode-style agents, commands, and MCP config."""
        from magent.plugins import import_compat_plugin

        result = import_compat_plugin("opencode", source, name=name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @import_app.command("claude")
    def plugin_import_claude_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Import Claude-style CLAUDE.md, agents, commands, and MCP config."""
        from magent.plugins import import_compat_plugin

        result = import_compat_plugin("claude", source, name=name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @import_app.command("codex-skill")
    def plugin_import_codex_skill_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Import a Codex-style SKILL.md pack as MagAgent skills."""
        from magent.plugins import import_compat_plugin

        result = import_compat_plugin("codex-skill", source, name=name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
