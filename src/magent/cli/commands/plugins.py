"""Plugin pack command registrations."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console

console = Console()


def register_plugin_commands(plugin_app: typer.Typer) -> None:
    import_app = typer.Typer(help="Import plugins from other agent ecosystems", name="import")
    mcp_app = typer.Typer(help="Import and apply MCP plugin packs", name="mcp")
    pi_app = typer.Typer(help="Inspect and bridge imported Pi packages", name="pi")
    plugin_app.add_typer(import_app, name="import")
    trust_app = typer.Typer(help="Public keys you trust to sign plugins.", no_args_is_help=True)
    registry_app = typer.Typer(help="Static plugin registries to search and install from.", no_args_is_help=True)
    plugin_app.add_typer(trust_app, name="trust")
    plugin_app.add_typer(registry_app, name="registry")

    @trust_app.command("add")
    def plugin_trust_add_cmd(
        key_id: str = typer.Argument(..., help="A name for the signer, e.g. acme."),
        public_key: str = typer.Argument(..., help="ed25519:<base64> from the publisher."),
        note: str = typer.Option("", "--note"),
    ) -> None:
        """Trust a publisher's public key (check its fingerprint with them first)."""
        from magent.plugin_signing import trust_key

        try:
            console.print_json(data=trust_key(key_id, public_key, note=note))
        except ValueError as error:
            console.print_json(data={"ok": False, "error": str(error)})
            raise typer.Exit(2) from error

    @trust_app.command("list")
    def plugin_trust_list_cmd() -> None:
        """List trusted plugin signing keys."""
        from magent.plugin_signing import list_trusted_keys

        console.print_json(data={"ok": True, "keys": list_trusted_keys()})

    @trust_app.command("remove")
    def plugin_trust_remove_cmd(key_id: str = typer.Argument(...)) -> None:
        """Stop trusting a signing key (installed plugins stay installed)."""
        from magent.plugin_signing import untrust_key

        result = untrust_key(key_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @registry_app.command("add")
    def plugin_registry_add_cmd(
        name: str = typer.Argument(...),
        location: str = typer.Argument(..., help="HTTPS URL or local path of index.json."),
    ) -> None:
        """Add a static plugin registry (its index is fetched once to check it)."""
        from magent.plugin_registry import RegistryError, add_registry

        try:
            console.print_json(data=add_registry(name, location))
        except RegistryError as error:
            console.print_json(data={"ok": False, "error": str(error)})
            raise typer.Exit(1) from error

    @registry_app.command("list")
    def plugin_registry_list_cmd() -> None:
        """List configured plugin registries."""
        from magent.plugin_registry import list_registries

        console.print_json(data={"ok": True, "registries": list_registries()})

    @registry_app.command("remove")
    def plugin_registry_remove_cmd(name: str = typer.Argument(...)) -> None:
        """Remove a plugin registry."""
        from magent.plugin_registry import RegistryError, remove_registry

        try:
            console.print_json(data=remove_registry(name))
        except RegistryError as error:
            console.print_json(data={"ok": False, "error": str(error)})
            raise typer.Exit(1) from error

    @registry_app.command("build")
    def plugin_registry_build_cmd(
        packs: Annotated[list[str], typer.Argument(help="Plugin directories to publish.")],
        out: str = typer.Option(..., "--out", help="Directory for index.json and archives."),
        name: str = typer.Option(..., "--name", help="Registry name."),
        key: str = typer.Option("", "--key", help="Sign each pack with this Ed25519 key first."),
        key_id: str = typer.Option("", "--key-id"),
    ) -> None:
        """Build a static registry (index.json plus .tar.gz archives) to host anywhere."""
        from pathlib import Path

        from magent.plugin_registry import RegistryError, build_registry

        try:
            result = build_registry(
                [Path(pack) for pack in packs],
                Path(out),
                name=name,
                sign_key=Path(key).expanduser() if key else None,
                key_id=key_id,
            )
        except (RegistryError, OSError, ValueError) as error:
            console.print_json(data={"ok": False, "error": str(error)})
            raise typer.Exit(1) from error
        console.print_json(data=result)
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
        source: str = typer.Argument(..., help="A plugin directory, or NAME[@VERSION] from a registry."),
        name: str = typer.Option("", "--name"),
        force: bool = typer.Option(False, "--force"),
        registry: str = typer.Option("", "--registry", help="Only look in this registry."),
        allow_unsigned: bool = typer.Option(
            False, "--allow-unsigned", help="Install a registry pack that has no signature."
        ),
        yes: bool = typer.Option(
            False, "--yes", "-y", help="Trust the signing key without asking (non-interactive)."
        ),
    ) -> None:
        """Install a plugin pack from a directory or a configured registry.

        Registry installs check the archive hash, the pack digest and the Ed25519
        signature. A pack signed by a key you have not trusted asks first.

        Examples: `magent plugin install ./my-pack`,
        `magent plugin install release-kit@1.2.0 --registry acme`.
        """
        from pathlib import Path

        from magent.plugins import install_plugin

        if Path(source).expanduser().is_dir():
            from magent.plugin_signing import verify_signature

            signature = verify_signature(Path(source).expanduser().resolve())
            if signature["status"] == "invalid":
                console.print_json(
                    data={"ok": False, "error": f"Signature check failed: {signature['reason']}"}
                )
                raise typer.Exit(1)
            result = install_plugin(source, name=name, force=force)
            if result.get("ok"):
                result["signature"] = signature
            console.print_json(data=result)
            if not result.get("ok"):
                raise typer.Exit(1)
            return
        from magent.plugin_registry import RegistryError, install_from_registry

        def confirm(entry: dict, verification: dict) -> bool:
            import sys

            if not sys.stdin.isatty():
                return False
            from rich.prompt import Confirm

            console.print(
                f"[yellow]{entry['name']} {entry.get('version', '')} is signed by "
                f"'{verification['key_id']}' ({verification['fingerprint']}), a key you do "
                "not trust yet.[/yellow]"
            )
            console.print(
                "It asks for permissions: " + (", ".join(entry.get("permissions") or []) or "none")
            )
            return Confirm.ask("Trust this key and install?", default=False)

        try:
            result = install_from_registry(
                source,
                registry=registry,
                allow_untrusted=yes,
                allow_unsigned=allow_unsigned,
                confirm_key=confirm,
                force=force,
            )
        except RegistryError as error:
            console.print_json(data={"ok": False, "error": str(error)})
            raise typer.Exit(1) from error
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @plugin_app.command("search")
    def plugin_search_cmd(
        query: str = typer.Argument("", help="Text to match in names and descriptions."),
        registry: str = typer.Option("", "--registry", help="Only search this registry."),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    ) -> None:
        """Search configured plugin registries."""
        from rich.table import Table

        from magent.plugin_registry import RegistryError, search

        try:
            results = search(query, registry=registry)
        except RegistryError as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1) from error
        if json_output:
            console.print_json(data={"ok": True, "plugins": results})
            return
        if not results:
            console.print("[dim]No plugins matched.[/dim]")
            return
        table = Table("Plugin", "Version", "Registry", "Signed by", "Permissions", "Description")
        for item in results:
            signature = item.get("signature") or {}
            table.add_row(
                str(item.get("name")),
                str(item.get("version")),
                item["registry"],
                str(signature.get("key_id") or "[red]unsigned[/red]"),
                ", ".join(item.get("permissions") or []) or "none",
                str(item.get("description") or ""),
            )
        console.print(table)
        console.print("[dim]Install with `magent plugin install NAME[@VERSION]`.[/dim]")

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
    def plugin_verify_cmd(
        path: str = typer.Argument(...),
        require_signature: bool = typer.Option(
            False, "--require-signature", help="Fail unless signed by a trusted key."
        ),
    ) -> None:
        """Verify a plugin's checksum, conformance and Ed25519 signature."""
        from pathlib import Path

        from magent.plugin_sdk import verify_plugin
        from magent.plugin_signing import verify_signature

        result = verify_plugin(path)
        signature = verify_signature(Path(path).expanduser().resolve())
        result["signature"] = signature
        if signature["status"] == "invalid" or (require_signature and not signature["ok"]):
            result["ok"] = False
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @plugin_app.command("keygen")
    def plugin_keygen_cmd(
        out: str = typer.Argument(..., help="Where to write the new private key (PEM)."),
    ) -> None:
        """Create an Ed25519 signing key for your plugins (kept by you, mode 0600)."""
        from pathlib import Path

        from magent.plugin_signing import generate_key

        try:
            result = generate_key(Path(out).expanduser())
        except FileExistsError as error:
            console.print_json(data={"ok": False, "error": str(error)})
            raise typer.Exit(1) from error
        console.print_json(data=result)
        console.print(
            "[dim]Share the public key and fingerprint; never share or commit the key file.[/dim]"
        )

    @plugin_app.command("sign")
    def plugin_sign_cmd(
        path: str = typer.Argument(..., help="Plugin directory to sign."),
        key: str = typer.Option(..., "--key", help="Ed25519 private key (PEM) from `plugin keygen`."),
        key_id: str = typer.Option(..., "--key-id", help="Name users will see, e.g. your org."),
    ) -> None:
        """Sign a plugin pack (writes magent-plugin.sig over its files and manifest)."""
        from pathlib import Path

        from magent.plugin_signing import sign_plugin

        try:
            result = sign_plugin(Path(path).expanduser().resolve(), Path(key).expanduser(), key_id=key_id)
        except (OSError, ValueError) as error:
            console.print_json(data={"ok": False, "error": str(error)})
            raise typer.Exit(1) from error
        console.print_json(data=result)

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
