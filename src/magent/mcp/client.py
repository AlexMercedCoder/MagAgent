"""MCP (Model Context Protocol) client — uses the official mcp Python SDK.

Each MCPClient manages ONE server subprocess (stdio transport).
Uses mcp.ClientSession which handles JSON-RPC 2.0, initialize handshake, etc.

Install: pip install "mcp[cli]>=1.0"
See: https://github.com/modelcontextprotocol/python-sdk
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("magent.mcp.client")


@dataclass
class MCPTool:
    """A tool exposed by an MCP server, adapted for MagAgent."""

    name: str  # original tool name, e.g. "create_issue"
    description: str
    input_schema: dict[str, Any]  # JSON Schema for parameters
    server_name: str  # which server owns this tool
    # Namespaced as "mcp__<server>__<tool>" to avoid conflicts with built-ins
    qualified_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.qualified_name = f"mcp__{self.server_name}__{self.name}"

    def to_openai_definition(self) -> dict[str, Any]:
        """Convert to an OpenAI-compatible function tool definition."""
        schema = (
            self.input_schema
            if self.input_schema is not None
            else {"type": "object", "properties": {}}
        )
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": f"[{self.server_name}] {self.description}",
                "parameters": schema,
            },
        }


class MCPClient:
    """
    Manages a single MCP server process via the official mcp SDK.

    Usage:
        client = MCPClient("github", "npx", ["-y", "@modelcontextprotocol/server-github"])
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("search_repositories", {"query": "MagAgent"})
        await client.disconnect()
    """

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 30.0,
    ):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        # Merge extra env vars on top of the current environment
        self.env = {**os.environ, **(env or {})} if env else None
        self.cwd = cwd
        self.timeout = timeout

        self._session: Any = None
        self._stack: AsyncExitStack | None = None
        self._tools: list[MCPTool] = []
        self._connected = False

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    async def connect(self) -> bool:
        """
        Start the server subprocess, perform the initialize handshake,
        and discover available tools.
        Returns True on success.
        """
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            log.error(
                'MCP SDK not installed. Run: pip install "mcp[cli]>=1.0"\n'
                'or: pip install "mag-agent[mcp]"'
            )
            return False

        try:
            params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=self.env,
            )
            self._stack = AsyncExitStack()
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            # SDK handles initialize request + notifications/initialized automatically
            await asyncio.wait_for(self._session.initialize(), timeout=self.timeout)
            self._connected = True

            # Discover tools immediately
            await self.list_tools()
            log.info(f"MCP [{self.server_name}] connected — {len(self._tools)} tools available")
            return True

        except TimeoutError:
            log.error(f"MCP [{self.server_name}] initialize timed out")
            await self.disconnect()
            return False
        except Exception as e:
            log.error(f"MCP [{self.server_name}] connect failed: {e}")
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Shut down the server subprocess and clean up."""
        if self._stack:
            with suppress(Exception):
                await self._stack.aclose()
        self._session = None
        self._stack = None
        self._connected = False
        log.debug(f"MCP [{self.server_name}] disconnected")

    @property
    def connected(self) -> bool:
        return self._connected

    # ─────────────────────────────────────────────
    # Tool discovery
    # ─────────────────────────────────────────────

    async def list_tools(self) -> list[MCPTool]:
        """Query the server for available tools. Caches results in self._tools."""
        if not self._session:
            return []
        try:
            result = await asyncio.wait_for(self._session.list_tools(), timeout=self.timeout)
            self._tools = [
                MCPTool(
                    name=t.name,
                    description=t.description or "",
                    input_schema=t.inputSchema
                    if isinstance(t.inputSchema, dict)
                    else t.inputSchema.model_dump()
                    if hasattr(t.inputSchema, "model_dump")
                    else {},
                    server_name=self.server_name,
                )
                for t in result.tools
            ]
            return self._tools
        except Exception as e:
            log.error(f"MCP [{self.server_name}] list_tools failed: {e}")
            return []

    @property
    def tools(self) -> list[MCPTool]:
        """Cached list of available tools."""
        return self._tools

    def get_tool(self, original_name: str) -> MCPTool | None:
        """Look up a tool by its original (non-qualified) name."""
        return next((t for t in self._tools if t.name == original_name), None)

    # ─────────────────────────────────────────────
    # Tool execution
    # ─────────────────────────────────────────────

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool on this server by its original name.
        Returns MagAgent-standard {ok, result} or {ok: False, error}.
        """
        if not self._session or not self._connected:
            return {"ok": False, "error": f"MCP [{self.server_name}] not connected"}

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=self.timeout,
            )

            # result.isError = True means tool-level error (not a JSON-RPC error)
            if result.isError:
                error_text = _extract_text(result.content)
                log.warning(f"MCP [{self.server_name}].{tool_name} tool error: {error_text}")
                return {"ok": False, "error": error_text, "server": self.server_name}

            text = _extract_text(result.content)
            return {"ok": True, "result": text, "server": self.server_name}

        except TimeoutError:
            return {"ok": False, "error": f"MCP [{self.server_name}].{tool_name} timed out"}
        except Exception as e:
            return {"ok": False, "error": f"MCP [{self.server_name}].{tool_name} error: {e}"}


def _extract_text(content_list: list[Any]) -> str:
    """Flatten MCP content items (TextContent, ImageContent, etc.) to a string."""
    parts = []
    for item in content_list:
        item_type = getattr(item, "type", None)
        if item_type == "text":
            parts.append(getattr(item, "text", ""))
        elif item_type == "image":
            parts.append(f"[image/{getattr(item, 'mimeType', 'unknown')}]")
        elif item_type == "resource":
            res = getattr(item, "resource", None)
            if res:
                uri = getattr(res, "uri", "?")
                text = getattr(res, "text", None)
                parts.append(f"[resource: {uri}]" + (f"\n{text}" if text else ""))
        else:
            parts.append(str(item))
    return "\n".join(p for p in parts if p)
