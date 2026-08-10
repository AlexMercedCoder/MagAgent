"""Plugin pack command registrations."""

from __future__ import annotations

import json

import typer
from rich.console import Console

console = Console()


def register_plugin_commands(plugin_app: typer.Typer) -> None:
    import_app = typer.Typer(help="Import plugins from other agent ecosystems", name="import")
    mcp_app = typer.Typer(help="Import and apply MCP plugin packs", name="mcp")
    pi_app = typer.Typer(help="Inspect and bridge imported Pi packages", name="pi")
    plugin_app.add_typer(import_app, name="import")
    plugin_app.add_typer(mcp_app, name="mcp")
    plugin_app.add_typer(pi_app, name="pi")

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

    @plugin_app.command("validate")
    def plugin_validate_cmd(
        path: str = typer.Argument(...),
        compatibility: bool = typer.Option(False, "--compatibility", help="Warn instead of failing for legacy manifest omissions."),
    ) -> None:
        """Run the plugin SDK manifest, permission, and contribution checks."""
        from magent.plugin_sdk import validate_plugin

        result = validate_plugin(path, strict=not compatibility)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @plugin_app.command("verify")
    def plugin_verify_cmd(path: str = typer.Argument(...)) -> None:
        """Verify a plugin's deterministic content checksum and conformance."""
        from magent.plugin_sdk import verify_plugin

        result = verify_plugin(path)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @plugin_app.command("grant")
    def plugin_grant_cmd(
        name: str = typer.Argument(...),
        permissions: str = typer.Option(..., "--permissions", help="Comma-separated reviewed permissions."),
        scope: str = typer.Option("project", "--scope", help="project or user"),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Grant reviewed plugin permissions at project or user scope."""
        from magent.plugins import set_plugin_grant

        result = set_plugin_grant(
            name,
            scope=scope,
            permissions=[item.strip() for item in permissions.split(",") if item.strip()],
            project=project,
        )
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @plugin_app.command("schema")
    def plugin_schema_cmd(output: str = typer.Option("", "--output", "-o")) -> None:
        """Print or write the versioned MagAgent plugin manifest schema."""
        from magent.plugin_sdk import MANIFEST_SCHEMA, write_schema

        if output:
            target = write_schema(output)
            console.print_json(data={"ok": True, "path": str(target), "schema": MANIFEST_SCHEMA["$id"]})
            return
        console.print_json(data=MANIFEST_SCHEMA)

    @plugin_app.command("registry-index")
    def plugin_registry_index_cmd(
        paths: list[str], output: str = typer.Option("", "--output", "-o")
    ) -> None:
        """Build deterministic registry metadata from local reviewed plugin packs."""
        from magent.plugin_sdk import build_registry_index

        result = build_registry_index(paths)
        if output:
            from pathlib import Path

            target = Path(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            result = {**result, "output": str(target)}
        console.print_json(data=result)

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

    @import_app.command("gemini")
    def plugin_import_gemini_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Import Gemini CLI-style extensions, commands, skills, and MCP config."""
        from magent.plugins import import_compat_plugin

        result = import_compat_plugin("gemini", source, name=name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @import_app.command("pi")
    def plugin_import_pi_cmd(
        source: str = typer.Argument(...),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Import portable Pi skills/prompts and inventory runtime extensions."""
        from magent.plugins import import_compat_plugin

        result = import_compat_plugin("pi", source, name=name, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @pi_app.command("bridge")
    def plugin_pi_bridge_cmd(
        name: str = typer.Argument(...),
        project: str = typer.Option(".", "--project", "-p"),
        mode: str = typer.Option("interactive", "--mode", help="interactive, rpc, or json"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show the reviewed command without starting Pi."),
    ) -> None:
        """Run preserved extensions through Pi's runtime after explicit approval."""
        from magent.plugins import run_pi_plugin_bridge

        result = run_pi_plugin_bridge(name, project=project, mode=mode, dry_run=dry_run)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
