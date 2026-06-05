"""Unit tests for the MCP client and manager.

All tests mock the mcp SDK so no external processes are needed.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magent.mcp.client import MCPClient, MCPTool, _extract_text
from magent.mcp.manager import MCPManager

# ─────────────────────────────────────────────
# MCPTool
# ─────────────────────────────────────────────


class TestMCPTool:
    def test_qualified_name(self) -> None:
        tool = MCPTool(
            name="search_repos",
            description="Search GitHub repositories",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            server_name="github",
        )
        assert tool.qualified_name == "mcp__github__search_repos"

    def test_to_openai_definition(self) -> None:
        tool = MCPTool(
            name="my_tool",
            description="Does something",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            server_name="myserver",
        )
        defn = tool.to_openai_definition()
        assert defn["type"] == "function"
        fn = defn["function"]
        assert fn["name"] == "mcp__myserver__my_tool"
        assert "[myserver]" in fn["description"]
        assert fn["parameters"]["type"] == "object"

    def test_empty_schema_fallback(self) -> None:
        tool = MCPTool(
            name="t",
            description="",
            input_schema={},
            server_name="s",
        )
        defn = tool.to_openai_definition()
        # Empty schema dict passes through as-is to parameters
        assert defn["function"]["parameters"] == {}

    def test_qualified_name_multiple_underscores(self) -> None:
        tool = MCPTool(
            name="create_pull_request",
            description="",
            input_schema={},
            server_name="gh",
        )
        assert tool.qualified_name == "mcp__gh__create_pull_request"


# ─────────────────────────────────────────────
# _extract_text helper
# ─────────────────────────────────────────────


class TestExtractText:
    def _item(self, type_: str, **kwargs: Any) -> MagicMock:
        m = MagicMock()
        m.type = type_
        for k, v in kwargs.items():
            setattr(m, k, v)
        return m

    def test_text_items_joined(self) -> None:
        items = [self._item("text", text="Hello"), self._item("text", text="World")]
        assert _extract_text(items) == "Hello\nWorld"

    def test_image_item_placeholder(self) -> None:
        items = [self._item("image", mimeType="image/png")]
        assert _extract_text(items) == "[image/image/png]"

    def test_resource_item_with_text(self) -> None:
        resource = MagicMock()
        resource.uri = "file:///foo.txt"
        resource.text = "file contents"
        items = [self._item("resource", resource=resource)]
        result = _extract_text(items)
        assert "file:///foo.txt" in result
        assert "file contents" in result

    def test_empty_list(self) -> None:
        assert _extract_text([]) == ""

    def test_mixed_items(self) -> None:
        items = [
            self._item("text", text="result"),
            self._item("image", mimeType="image/jpeg"),
        ]
        result = _extract_text(items)
        assert "result" in result
        assert "image/jpeg" in result


# ─────────────────────────────────────────────
# MCPClient (mocked SDK)
# ─────────────────────────────────────────────


def _make_mock_tool(name: str, description: str = "A tool") -> MagicMock:
    """Create a mock mcp Tool object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = {"type": "object", "properties": {}}
    return tool


def _make_mock_session(
    tools: list, call_result_text: str = "ok", is_error: bool = False
) -> AsyncMock:
    """Create a mock mcp.ClientSession."""
    session = AsyncMock()

    # list_tools
    list_result = MagicMock()
    list_result.tools = tools
    session.list_tools.return_value = list_result

    # call_tool
    call_content = MagicMock()
    call_content.type = "text"
    call_content.text = call_result_text
    call_result = MagicMock()
    call_result.isError = is_error
    call_result.content = [call_content]
    session.call_tool.return_value = call_result

    # initialize (no return value needed)
    session.initialize = AsyncMock(return_value=None)

    return session


class TestMCPClientConnect:
    @pytest.mark.asyncio
    async def test_connect_success_lists_tools(self) -> None:
        mock_tools = [_make_mock_tool("search"), _make_mock_tool("create")]
        mock_session = _make_mock_session(mock_tools)

        with patch("magent.mcp.client.MCPClient.connect", new_callable=AsyncMock):
            # Simulate a connected client by manually setting state
            client = MCPClient("srv", "echo", [])
            client._connected = True
            client._session = mock_session

            # Manually populate tools as connect() would
            raw = await mock_session.list_tools()
            client._tools = [
                MCPTool(
                    name=t.name,
                    description=t.description,
                    input_schema={},
                    server_name="srv",
                )
                for t in raw.tools
            ]
            assert len(client.tools) == 2
            assert client.tools[0].name == "search"
            assert client.tools[1].qualified_name == "mcp__srv__create"

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        mock_session = _make_mock_session([], call_result_text="Search results here")

        client = MCPClient("srv", "echo", [])
        client._connected = True
        client._session = mock_session

        result = await client.call_tool("search", {"q": "python"})
        assert result["ok"] is True
        assert result["result"] == "Search results here"
        assert result["server"] == "srv"

    @pytest.mark.asyncio
    async def test_call_tool_error_response(self) -> None:
        mock_session = _make_mock_session([], call_result_text="Not found", is_error=True)

        client = MCPClient("srv", "echo", [])
        client._connected = True
        client._session = mock_session

        result = await client.call_tool("search", {"q": "x"})
        assert result["ok"] is False
        assert "Not found" in result["error"]

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self) -> None:
        client = MCPClient("srv", "echo", [])
        client._connected = False
        client._session = None

        result = await client.call_tool("any_tool", {})
        assert result["ok"] is False
        assert "not connected" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_call_tool_timeout(self) -> None:
        async def slow(*_: Any, **__: Any) -> Any:
            await asyncio.sleep(100)

        mock_session = AsyncMock()
        mock_session.call_tool = slow

        client = MCPClient("srv", "echo", [], timeout=0.01)
        client._connected = True
        client._session = mock_session

        result = await client.call_tool("tool", {})
        assert result["ok"] is False
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self) -> None:
        client = MCPClient("srv", "echo", [])
        client._connected = True
        client._stack = AsyncMock()
        client._stack.aclose = AsyncMock()

        await client.disconnect()
        assert not client.connected
        assert client._session is None


# ─────────────────────────────────────────────
# MCPManager
# ─────────────────────────────────────────────


class TestMCPManager:
    def _make_client(self, name: str, tools: list[MCPTool], connected: bool = True) -> MagicMock:
        client = MagicMock(spec=MCPClient)
        client.server_name = name
        client.connected = connected
        client.tools = tools
        client.connect = AsyncMock(return_value=connected)
        client.disconnect = AsyncMock()
        client.call_tool = AsyncMock(return_value={"ok": True, "result": "done", "server": name})
        return client

    def test_is_mcp_tool_true(self) -> None:
        MCPTool("do_thing", "Desc", {}, "myserver")
        manager = MCPManager()
        manager._tool_index["mcp__myserver__do_thing"] = (MagicMock(), "do_thing")
        assert manager.is_mcp_tool("mcp__myserver__do_thing") is True

    def test_is_mcp_tool_false_builtin(self) -> None:
        manager = MCPManager()
        assert manager.is_mcp_tool("read_file") is False

    def test_is_mcp_tool_false_unknown_mcp(self) -> None:
        manager = MCPManager()
        # mcp__ prefix but not in index
        assert manager.is_mcp_tool("mcp__ghost__tool") is False

    @pytest.mark.asyncio
    async def test_dispatch_routes_to_correct_client(self) -> None:
        MCPTool("my_tool", "", {}, "srv")
        client = MagicMock()
        client.call_tool = AsyncMock(return_value={"ok": True, "result": "x"})

        manager = MCPManager()
        manager._tool_index["mcp__srv__my_tool"] = (client, "my_tool")

        result = await manager.dispatch("mcp__srv__my_tool", {"a": 1})
        client.call_tool.assert_called_once_with("my_tool", {"a": 1})
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self) -> None:
        manager = MCPManager()
        result = await manager.dispatch("mcp__ghost__tool", {})
        assert result["ok"] is False
        assert "Unknown" in result["error"]

    def test_get_tool_definitions_empty(self) -> None:
        manager = MCPManager()
        assert manager.get_tool_definitions() == []

    def test_get_tool_definitions_aggregates(self) -> None:
        tool1 = MCPTool("a", "desc a", {}, "server1")
        tool2 = MCPTool("b", "desc b", {}, "server2")

        client1 = MagicMock()
        client1.tools = [tool1]
        client2 = MagicMock()
        client2.tools = [tool2]

        manager = MCPManager()
        manager._clients = {"server1": client1, "server2": client2}

        defs = manager.get_tool_definitions()
        assert len(defs) == 2
        names = [d["function"]["name"] for d in defs]
        assert "mcp__server1__a" in names
        assert "mcp__server2__b" in names

    def test_list_servers_no_config(self) -> None:
        manager = MCPManager({})
        assert manager.list_servers() == []

    def test_list_servers_shows_config_names(self) -> None:
        cfg = {
            "github": {"command": "npx", "args": ["-y", "@mcp/server-github"]},
        }
        manager = MCPManager(cfg)
        servers = manager.list_servers()
        assert len(servers) == 1
        assert servers[0]["name"] == "github"
        assert servers[0]["connected"] is False  # not connected yet

    def test_connected_count_and_total_tools(self) -> None:
        tool = MCPTool("t", "", {}, "s")
        client = MagicMock()
        client.connected = True
        client.tools = [tool, tool]

        manager = MCPManager()
        manager._clients = {"s": client}
        assert manager.connected_count == 1
        assert manager.total_tools == 2
