"""MCP package init."""

from magent.mcp.catalog import MCPCatalogFreshness, MCPPrompt, MCPResource
from magent.mcp.client import MCPClient, MCPTool
from magent.mcp.manager import MCPManager
from magent.mcp.profile import (
    MCPConfigError,
    MCPProtocolMode,
    MCPServerProfile,
    MCPTransport,
    normalize_mcp_servers,
)

__all__ = [
    "MCPClient",
    "MCPCatalogFreshness",
    "MCPPrompt",
    "MCPResource",
    "MCPConfigError",
    "MCPManager",
    "MCPProtocolMode",
    "MCPServerProfile",
    "MCPTool",
    "MCPTransport",
    "normalize_mcp_servers",
]
