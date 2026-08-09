"""MCP Manager — orchestrates multiple MCP server connections for a session.

Reads [mcp.servers.*] from config, connects all servers on session start,
aggregates tool lists, and routes tool calls to the correct server.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console

from magent.mcp.catalog import MCPPrompt, MCPResource
from magent.mcp.client import MCPClient, MCPInputHandler, MCPTool
from magent.mcp.profile import MCPServerProfile, normalize_mcp_servers

console = Console()
log = logging.getLogger("magent.mcp.manager")


class MCPManager:
    """
    Manages all MCP server connections for a MagAgent session.

    Typical flow in AgentSession:
        manager = MCPManager(config.get("mcp", {}).get("servers", {}))
        await manager.start_all()
        tool_defs += manager.get_tool_definitions()
        # ... in dispatch:
        if tool_name.startswith("mcp__"):
            return await manager.dispatch(tool_name, args)
        # on session end:
        await manager.stop_all()
    """

    def __init__(
        self,
        servers_config: dict[str, dict[str, Any]] | None = None,
        *,
        input_handler: MCPInputHandler | None = None,
    ):
        """
        servers_config: the [mcp.servers] dict from config.toml, e.g.:
        {
          "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_TOKEN": "..."}},
          "postgres": {"command": "npx", "args": [...], "timeout": 60},
        }
        """
        self._config = servers_config or {}
        self._input_handler = input_handler
        self._profiles, self._config_errors = normalize_mcp_servers(self._config)
        self._clients: dict[str, MCPClient] = {}  # server_name → MCPClient
        self._tool_index: dict[
            str, tuple[MCPClient, str]
        ] = {}  # qualified_name → (client, original_name)

    async def start_all(self) -> dict[str, bool]:
        """
        Connect to all configured MCP servers concurrently.
        Returns {server_name: success} map.
        """
        if not self._config:
            return {}

        async def _connect_one(name: str, profile: MCPServerProfile) -> tuple[str, bool]:
            client = MCPClient.from_profile(profile)
            client.input_handler = self._input_handler
            ok = await client.connect()
            self._clients[name] = client
            if ok:
                # Index all tools for fast dispatch
                for tool in client.tools:
                    self._tool_index[tool.qualified_name] = (client, tool.name)
            return name, ok

        results = await asyncio.gather(
            *(_connect_one(name, profile) for name, profile in self._profiles.items()),
            return_exceptions=False,
        )

        status = {name: False for name in self._config_errors}
        status.update(results)
        connected = sum(1 for ok in status.values() if ok)
        total_tools = sum(len(c.tools) for c in self._clients.values())

        if self._clients:
            console.print(
                f"  [dim]🔌 MCP: {connected}/{len(self._config)} servers connected, "
                f"{total_tools} tools available[/dim]"
            )

        return status

    async def stop_all(self) -> None:
        """Disconnect all MCP servers."""
        await asyncio.gather(
            *(client.disconnect() for client in self._clients.values()),
            return_exceptions=True,
        )
        self._clients.clear()
        self._tool_index.clear()

    # ─────────────────────────────────────────────
    # Tool interface (for AgentSession)
    # ─────────────────────────────────────────────

    def get_all_tools(self) -> list[MCPTool]:
        """Return all MCPTool objects from all connected servers."""
        tools = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools

    async def list_prompts(
        self, server_name: str | None = None, *, refresh: bool = False
    ) -> list[MCPPrompt]:
        """Return deterministic prompt metadata from connected servers."""
        clients = self._selected_clients(server_name)
        groups = await asyncio.gather(
            *(client.list_prompts(refresh=refresh) for client in clients),
            return_exceptions=False,
        )
        return sorted(
            (item for group in groups for item in group),
            key=lambda item: (item.server_name.casefold(), item.name.casefold()),
        )

    async def list_resources(
        self,
        server_name: str | None = None,
        *,
        refresh: bool = False,
        include_templates: bool = True,
    ) -> list[MCPResource]:
        """Return resource and optional template metadata from connected servers."""
        clients = self._selected_clients(server_name)
        resources = await asyncio.gather(
            *(client.list_resources(refresh=refresh) for client in clients),
            return_exceptions=False,
        )
        templates: list[list[MCPResource]] = []
        if include_templates:
            templates = await asyncio.gather(
                *(client.list_resource_templates(refresh=refresh) for client in clients),
                return_exceptions=False,
            )
        return sorted(
            (item for group in (*resources, *templates) for item in group),
            key=lambda item: (item.server_name.casefold(), item.name.casefold(), item.uri),
        )

    async def get_prompt(
        self, server_name: str, name: str, arguments: dict[str, str] | None = None
    ) -> dict[str, Any]:
        client = self._clients.get(server_name)
        if not client or not client.connected:
            return {"ok": False, "error": f"MCP server '{server_name}' is not connected"}
        return await client.get_prompt(name, arguments)

    async def complete(
        self,
        server_name: str,
        reference: str,
        argument: dict[str, str],
        *,
        reference_type: str = "prompt",
        context_arguments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        client = self._clients.get(server_name)
        if not client or not client.connected:
            return {"ok": False, "error": f"MCP server '{server_name}' is not connected"}
        return await client.complete(
            reference,
            argument,
            reference_type=reference_type,
            context_arguments=context_arguments,
        )

    async def read_resource(
        self, server_name: str, uri: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        client = self._clients.get(server_name)
        if not client or not client.connected:
            return {"ok": False, "error": f"MCP server '{server_name}' is not connected"}
        return await client.read_resource(uri, refresh=refresh)

    def catalog_status(self) -> dict[str, Any]:
        return {name: client.catalog_status() for name, client in sorted(self._clients.items())}

    def _selected_clients(self, server_name: str | None) -> list[MCPClient]:
        if server_name is None:
            return [client for client in self._clients.values() if client.connected]
        client = self._clients.get(server_name)
        return [client] if client and client.connected else []

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function definitions for all MCP tools."""
        return [tool.to_openai_definition() for tool in self.get_all_tools()]

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to an MCP server."""
        return tool_name.startswith("mcp__") and tool_name in self._tool_index

    async def dispatch(self, qualified_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """
        Route a tool call to the correct MCP server.
        qualified_name format: "mcp__<server_name>__<tool_name>"
        """
        entry = self._tool_index.get(qualified_name)
        if not entry:
            return {"ok": False, "error": f"Unknown MCP tool: {qualified_name}"}

        client, original_name = entry
        log.debug(f"MCP dispatch: {qualified_name} → [{client.server_name}].{original_name}")
        return await client.call_tool(original_name, args)

    # ─────────────────────────────────────────────
    # Inspection / CLI
    # ─────────────────────────────────────────────

    def list_servers(self) -> list[dict[str, Any]]:
        """Return a list of server status dicts for the CLI."""
        result = []
        for name in self._config:
            client = self._clients.get(name)
            profile = self._profiles.get(name)
            if client:
                result.append(client.public_status())
                continue
            result.append(
                {
                    "name": name,
                    "transport": profile.transport.value if profile else "invalid",
                    "protocol_mode": profile.protocol_mode.value if profile else "invalid",
                    "selected_era": "",
                    "protocol_version": "",
                    "endpoint": profile.public_endpoint if profile else "",
                    "connected": False,
                    "tools": [],
                    "catalogs": {},
                    "error": self._config_errors.get(name, "not connected"),
                }
            )
        return result

    @property
    def connected_count(self) -> int:
        return sum(1 for c in self._clients.values() if c.connected)

    @property
    def total_tools(self) -> int:
        return sum(len(c.tools) for c in self._clients.values())
