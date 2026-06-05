"""MCP Manager — orchestrates multiple MCP server connections for a session.

Reads [mcp.servers.*] from config, connects all servers on session start,
aggregates tool lists, and routes tool calls to the correct server.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console

from magent.mcp.client import MCPClient, MCPTool

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

    def __init__(self, servers_config: dict[str, dict[str, Any]] | None = None):
        """
        servers_config: the [mcp.servers] dict from config.toml, e.g.:
        {
          "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {"GITHUB_TOKEN": "..."}},
          "postgres": {"command": "npx", "args": [...], "timeout": 60},
        }
        """
        self._config = servers_config or {}
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

        async def _connect_one(name: str, cfg: dict[str, Any]) -> tuple[str, bool]:
            client = MCPClient(
                server_name=name,
                command=cfg["command"],
                args=cfg.get("args", []),
                env=cfg.get("env"),
                timeout=cfg.get("timeout", 30.0),
            )
            ok = await client.connect()
            if ok:
                self._clients[name] = client
                # Index all tools for fast dispatch
                for tool in client.tools:
                    self._tool_index[tool.qualified_name] = (client, tool.name)
            return name, ok

        results = await asyncio.gather(
            *(_connect_one(n, c) for n, c in self._config.items()),
            return_exceptions=False,
        )

        status = dict(results)
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
        for name, cfg in self._config.items():
            client = self._clients.get(name)
            result.append(
                {
                    "name": name,
                    "command": cfg.get("command", "?"),
                    "args": cfg.get("args", []),
                    "connected": client is not None and client.connected,
                    "tools": [t.name for t in client.tools] if client else [],
                }
            )
        return result

    @property
    def connected_count(self) -> int:
        return sum(1 for c in self._clients.values() if c.connected)

    @property
    def total_tools(self) -> int:
        return sum(len(c.tools) for c in self._clients.values())
