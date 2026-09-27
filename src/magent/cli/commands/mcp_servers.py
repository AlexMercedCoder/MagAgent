"""MCP server management commands."""

from __future__ import annotations

import asyncio
import contextlib
import json

import typer
from rich.table import Table

from magent.cli.app import (
    mcp_app,
)
from magent.cli.shared import console
from magent.config import (
    CONFIG_DIR,
    get_current_user,
    load_config,
)

EXAMPLE_MCP_CONFIG = """
# Add to ~/.config/magent/config.toml:

[mcp.servers.github]
transport = "stdio"
protocol_mode = "auto" # auto | modern | legacy
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "ghp_your_token_here" }

[mcp.servers.filesystem]
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]

[mcp.servers.postgres]
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"]
timeout = 60

# Modern Streamable HTTP configuration:
# [mcp.servers.remote]
# transport = "streamable-http"
# protocol_mode = "modern"
# url = "https://example.com/mcp"
# headers = { Authorization = "Bearer ${MCP_TOKEN}" }

# Browse more servers: https://github.com/modelcontextprotocol/servers
"""


@mcp_app.command("list")
def mcp_list(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full tool schemas"),
) -> None:
    """List all configured MCP servers and their available tools."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user. Run 'magent setup' first.[/red]")
        raise typer.Exit(1)

    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if not mcp_servers:
        console.print("[yellow]No MCP servers configured.[/yellow]")
        console.print("\nExample config:")
        console.print(EXAMPLE_MCP_CONFIG, markup=False, highlight=False)
        return

    async def _list() -> None:
        from magent.mcp import MCPManager

        manager = MCPManager(mcp_servers)
        console.print(f"\n[bold]Connecting to {len(mcp_servers)} MCP server(s)...[/bold]")
        await manager.start_all()

        for server_info in manager.list_servers():
            name = server_info["name"]
            ok = server_info["connected"]
            endpoint = server_info["endpoint"]
            transport = server_info["transport"]
            configured_mode = server_info["protocol_mode"]
            selected_era = server_info["selected_era"] or "-"
            protocol_version = server_info["protocol_version"] or "-"
            tools = server_info["tools"]
            error = server_info["error"]

            icon = "[green]●[/green]" if ok else "[red]●[/red]"
            console.print(f"\n  {icon} [bold]{name}[/bold]  [dim]{endpoint}[/dim]")
            console.print(
                f"    [dim]transport={transport} configured={configured_mode} "
                f"selected={selected_era} version={protocol_version}[/dim]"
            )

            if ok and tools:
                table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
                table.add_column("Tool", style="white")
                table.add_column("Qualified Name", style="dim")
                table.add_column("Description")
                for tool in manager.tools_for(name):
                    table.add_row(
                        tool.name,
                        tool.qualified_name,
                        (tool.description or "-")[:80],
                    )
                console.print(table)
            elif not ok:
                console.print(f"    [red]{error or 'Connection failed'}[/red]")
            else:
                console.print("    [dim](no tools)[/dim]")

        await manager.stop_all()

    asyncio.run(_list())


@mcp_app.command("test")
def mcp_test(
    server: str = typer.Argument(..., help="Server name from config (e.g. github)"),
) -> None:
    """Test connection to a specific MCP server and list its tools."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)

    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        console.print(f"Configured: {list(mcp_servers.keys()) or '(none)'}")
        raise typer.Exit(1)

    async def _test() -> None:
        from magent.mcp import MCPClient, MCPConfigError, MCPServerProfile

        srv_cfg = mcp_servers[server]
        try:
            profile = MCPServerProfile.from_config(server, srv_cfg)
        except MCPConfigError as exc:
            console.print(f"[red]Invalid MCP configuration: {exc}[/red]")
            raise typer.Exit(1) from exc
        client = MCPClient.from_profile(profile)
        console.print(f"\nConnecting to [bold]{server}[/bold]...")
        console.print(
            f"[dim]transport={profile.transport.value} "
            f"protocol_mode={profile.protocol_mode.value} endpoint={profile.public_endpoint}[/dim]"
        )
        ok = await client.connect()
        # From here on the server subprocess exists, so every exit path has to
        # disconnect — including the failure paths, which used to leak it.
        try:
            if not ok:
                console.print(f"[red]✗ {client.last_error or 'Connection failed.'}[/red]")
                raise typer.Exit(1)

            console.print(
                f"[green]✓ Connected using {client.selected_era} MCP "
                f"({client.selected_protocol_version}) — {len(client.tools)} tools:[/green]"
            )
            for tool in client.tools:
                console.print(f"  [bold]{tool.name}[/bold] — {tool.description}")
                console.print(f"    [dim]{tool.qualified_name}[/dim]")
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()
        console.print("\n[dim]Connection closed.[/dim]")

    asyncio.run(_test())


@mcp_app.command("catalog")
def mcp_catalog(
    server: str | None = typer.Argument(None, help="Optional configured server name"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass cached MCP catalogs"),
) -> None:
    """Browse MCP prompts and resources with cache freshness."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server and server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)

    async def _catalog() -> None:
        from magent.mcp import MCPManager

        manager = MCPManager(mcp_servers)
        await manager.start_all()
        try:
            prompts = await manager.list_prompts(server, refresh=refresh)
            resources = await manager.list_resources(server, refresh=refresh)

            prompt_table = Table("Server", "Prompt", "Arguments", "Description", title="Prompts")
            for prompt in prompts:
                arguments = ", ".join(
                    str(item.get("name")) for item in prompt.arguments if item.get("name")
                )
                prompt_table.add_row(
                    prompt.server_name,
                    prompt.name,
                    arguments or "-",
                    prompt.description or "-",
                )
            console.print(prompt_table if prompts else "[dim]No prompts advertised.[/dim]")

            resource_table = Table(
                "Server", "Resource", "URI / Template", "Type", title="Resources"
            )
            for resource in resources:
                resource_table.add_row(
                    resource.server_name,
                    resource.name or "-",
                    resource.uri,
                    "template" if resource.template else (resource.mime_type or "resource"),
                )
            console.print(resource_table if resources else "[dim]No resources advertised.[/dim]")

            for name, catalogs in manager.catalog_status().items():
                if server and name != server:
                    continue
                console.print(f"\n[bold]{name} freshness[/bold]")
                for kind, status in catalogs.items():
                    freshness = status.get("freshness") or {}
                    state = "fresh" if freshness.get("fresh") else "stale/unclaimed"
                    ttl = freshness.get("ttl_ms", 0)
                    error = status.get("error")
                    detail = f"{status['count']} items, {state}, ttl={ttl}ms"
                    if error:
                        detail += f", {error}"
                    console.print(f"  {kind}: {detail}", markup=False)
        finally:
            await manager.stop_all()

    asyncio.run(_catalog())


@mcp_app.command("resource")
def mcp_resource(
    server: str = typer.Argument(..., help="Configured MCP server name"),
    uri: str = typer.Argument(..., help="Resource URI"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass the resource cache"),
) -> None:
    """Read one MCP resource in a terminal-friendly format."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)

    async def _resource() -> None:
        from rich.text import Text

        from magent.mcp import MCPManager

        manager = MCPManager({server: mcp_servers[server]})
        await manager.start_all()
        try:
            result = await manager.read_resource(server, uri, refresh=refresh)
            if not result.get("ok"):
                console.print(f"[red]{result.get('error', 'Resource read failed')}[/red]")
                return
            console.print(f"\n[bold]{uri}[/bold]")
            for content in result.get("contents") or []:
                if not isinstance(content, dict):
                    continue
                mime = content.get("mime_type") or content.get("mimeType") or "unknown"
                console.print(f"[dim]{mime}[/dim]")
                if isinstance(content.get("text"), str):
                    console.print(Text(content["text"]))
                elif isinstance(content.get("blob"), str):
                    console.print(
                        f"[dim]Binary resource: {len(content['blob'])} base64 characters[/dim]"
                    )
            if result.get("truncated"):
                console.print("[yellow]Resource output was truncated at the safety limit.[/yellow]")
            cache = result.get("cache") or {}
            console.print(
                f"[dim]cache={cache.get('cache_scope', 'private')} "
                f"ttl={cache.get('ttl_ms', 0)}ms[/dim]"
            )
        finally:
            await manager.stop_all()

    asyncio.run(_resource())


@mcp_app.command("prompt")
def mcp_prompt(
    server: str = typer.Argument(..., help="Configured MCP server name"),
    name: str = typer.Argument(..., help="Prompt name"),
    arguments_json: str = typer.Option("{}", "--arguments", help="Prompt arguments as JSON"),
) -> None:
    """Render one MCP prompt while clearly identifying it as untrusted content."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)
    try:
        raw_arguments = json.loads(arguments_json)
        if not isinstance(raw_arguments, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw_arguments.items()
        ):
            raise ValueError("arguments must be a JSON object with string values")
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(f"[red]Invalid --arguments: {exc}[/red]")
        raise typer.Exit(2) from exc

    async def _prompt() -> None:
        from rich.text import Text

        from magent.mcp import MCPManager

        manager = MCPManager({server: mcp_servers[server]})
        await manager.start_all()
        try:
            result = await manager.get_prompt(server, name, raw_arguments)
            if not result.get("ok"):
                console.print(f"[red]{result.get('error', 'Prompt request failed')}[/red]")
                return
            console.print("[yellow]Untrusted MCP prompt content[/yellow]")
            if result.get("description"):
                console.print(Text(str(result["description"]), style="dim"))
            for message in result.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                console.print(f"\n[bold]{message.get('role', 'message')}[/bold]")
                content = message.get("content") or {}
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    console.print(Text(content["text"]))
                else:
                    console.print_json(data=content)
        finally:
            await manager.stop_all()

    asyncio.run(_prompt())


@mcp_app.command("complete")
def mcp_complete(
    server: str = typer.Argument(..., help="Configured MCP server name"),
    reference: str = typer.Argument(..., help="Prompt name or resource-template URI"),
    name: str = typer.Option(..., "--name", help="Argument name being completed"),
    value: str = typer.Option("", "--value", help="Partial argument value"),
    resource: bool = typer.Option(False, "--resource", help="Complete a resource template"),
    context_json: str = typer.Option("{}", "--context", help="Other arguments as JSON"),
) -> None:
    """Complete a prompt or resource-template argument through MCP."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)
    try:
        context = json.loads(context_json)
        if not isinstance(context, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in context.items()
        ):
            raise ValueError("context must be a JSON object with string values")
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(f"[red]Invalid --context: {exc}[/red]")
        raise typer.Exit(2) from exc

    async def _complete() -> None:
        from magent.mcp import MCPManager

        manager = MCPManager({server: mcp_servers[server]})
        await manager.start_all()
        try:
            result = await manager.complete(
                server,
                reference,
                {"name": name, "value": value},
                reference_type="resource" if resource else "prompt",
                context_arguments=context,
            )
            if not result.get("ok"):
                console.print(f"[red]{result.get('error', 'Completion failed')}[/red]")
                return
            completion = result.get("completion") or {}
            values = completion.get("values") or []
            for item in values:
                console.print(str(item), markup=False, highlight=False)
            if not values:
                console.print("[dim]No completions returned.[/dim]")
            if completion.get("has_more") or completion.get("hasMore"):
                console.print("[dim]The server has additional completions.[/dim]")
        finally:
            await manager.stop_all()

    asyncio.run(_complete())


@mcp_app.command("init")
def mcp_init() -> None:
    """Print an example MCP config block for config.toml."""
    console.print("\n[bold]Example MCP configuration:[/bold]")
    console.print(EXAMPLE_MCP_CONFIG, markup=False, highlight=False)
    console.print(f"[dim]Config: {CONFIG_DIR / 'config.toml'}[/dim]")
    console.print("[dim]Browse servers: https://github.com/modelcontextprotocol/servers[/dim]\n")
