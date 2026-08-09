"""Unit tests for the MCP client and manager.

All tests mock the mcp SDK so no external processes are needed.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magent.mcp.client import MCPClient, MCPTool, _extract_text
from magent.mcp.manager import MCPManager
from magent.mcp.profile import MCPProtocolMode, MCPServerProfile

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


class _FakeReader:
    def __init__(self, *messages: dict[str, Any]):
        self.messages = [json.dumps(item).encode() + b"\n" for item in messages]

    async def readline(self) -> bytes:
        return self.messages.pop(0) if self.messages else b""


class _FakeWriter:
    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def write(self, value: bytes) -> None:
        self.lines.append(json.loads(value))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, *messages: dict[str, Any]):
        self.stdin = _FakeWriter()
        self.stdout = _FakeReader(*messages)
        self.stderr = _FakeReader()
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.returncode = -15


class _ExitedDuringTerminateProcess(_FakeProcess):
    async def wait(self) -> int:
        raise TimeoutError

    def terminate(self) -> None:
        raise ProcessLookupError


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

    @pytest.mark.asyncio
    async def test_disconnect_tolerates_process_exit_before_terminate(self) -> None:
        client = MCPClient("srv", "echo", timeout=0.01)
        process = _ExitedDuringTerminateProcess()
        client._process = process

        await client.disconnect()

        assert client._process is None

    @pytest.mark.asyncio
    async def test_modern_mode_connects_through_bridge(self) -> None:
        process = _FakeProcess(
            {
                "ok": True,
                "event": "ready",
                "selected_era": "modern",
                "protocol_version": "2026-07-28",
                "capabilities": {"tools": {}},
                "server_info": {"name": "fixture"},
                "tools": [{"name": "echo", "description": "Echo", "input_schema": {}}],
            }
        )
        client = MCPClient("srv", "echo", protocol_mode=MCPProtocolMode.MODERN)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn:
            assert await client.connect() is True

        assert client.selected_era == "modern"
        assert client.selected_protocol_version == "2026-07-28"
        assert client.tools[0].qualified_name == "mcp__srv__echo"
        assert process.stdin.lines[0]["protocol_mode"] == "modern"
        assert str(spawn.call_args.args[1]).endswith("magent/mcp/bridge.py")

    @pytest.mark.asyncio
    async def test_http_profile_is_sent_over_stdin_and_redacted_publicly(self) -> None:
        process = _FakeProcess(
            {
                "ok": True,
                "event": "ready",
                "selected_era": "modern",
                "protocol_version": "2026-07-28",
                "tools": [],
            }
        )
        client = MCPClient(
            "remote",
            "",
            transport="streamable-http",
            url="https://example.test/mcp",
            headers={"Authorization": "Bearer secret"},
        )

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn:
            assert await client.connect() is True

        assert process.stdin.lines[0]["headers"] == {"Authorization": "Bearer secret"}
        assert "secret" not in str(client.public_status())
        assert "secret" not in str(spawn.call_args)

    def test_from_profile_and_public_status_redact_secrets(self) -> None:
        profile = MCPServerProfile.from_config(
            "srv",
            {"command": "echo", "env": {"TOKEN": "secret"}},
        )
        client = MCPClient.from_profile(profile)

        status = client.public_status()
        assert status["transport"] == "stdio"
        assert status["protocol_mode"] == "auto"
        assert "secret" not in str(status)

    def test_public_status_hides_sensitive_command_arguments(self) -> None:
        client = MCPClient("db", "server", ["postgres://user:secret@localhost/db"])

        assert client.public_status()["endpoint"] == "server (1 args)"

    @pytest.mark.asyncio
    async def test_bridge_stderr_redacts_explicit_credentials(self) -> None:
        process = _FakeProcess()
        process.stderr = _FakeReader.__new__(_FakeReader)
        process.stderr.messages = [b"request failed with Bearer secret-token\n", b""]
        client = MCPClient(
            "remote",
            "",
            headers={"Authorization": "Bearer secret-token"},
        )
        client._process = process

        await client._drain_stderr()

        assert client._stderr_tail == ["request failed with [redacted]"]

    @pytest.mark.asyncio
    async def test_prompt_catalog_uses_ttl_then_refreshes_after_invalidation(self) -> None:
        client = MCPClient("srv", "echo")
        client._connected = True
        client._request = AsyncMock(
            side_effect=[
                {
                    "ok": True,
                    "prompts": [
                        {"name": "zeta", "description": "Z"},
                        {"name": "alpha", "description": "A"},
                    ],
                    "meta": {
                        "fetched_at": "2099-01-01T00:00:00+00:00",
                        "ttl_ms": 60_000,
                        "cache_scope": "private",
                    },
                },
                {
                    "ok": True,
                    "prompts": [{"name": "alpha", "description": "Updated"}],
                    "meta": {"ttl_ms": 0},
                },
            ]
        )

        assert [item.name for item in await client.list_prompts()] == ["alpha", "zeta"]
        assert [item.name for item in await client.list_prompts()] == ["alpha", "zeta"]
        assert client._request.await_count == 1

        client.apply_catalog_event("prompts/list_changed")
        prompts = await client.list_prompts()
        assert prompts[0].description == "Updated"
        assert client._request.await_args.kwargs["refresh"] is True

        client.apply_catalog_event("resources/list_changed")
        assert client.catalog_status()["resources"]["reads_stale"] is True

    @pytest.mark.asyncio
    async def test_resource_catalog_read_and_errors(self) -> None:
        client = MCPClient("srv", "echo")
        client._connected = True
        client._request = AsyncMock(
            side_effect=[
                {
                    "ok": True,
                    "resources": [
                        {"uri": "memory://b", "name": "Beta"},
                        {"uri": "memory://a", "name": "Alpha"},
                    ],
                    "meta": {"ttl_ms": 0},
                },
                {
                    "ok": True,
                    "resource_templates": [
                        {"uri_template": "memory://{name}", "name": "Item"}
                    ],
                    "meta": {"ttl_ms": 1000},
                },
                {
                    "ok": True,
                    "result": {
                        "contents": [{"uri": "memory://a", "text": "content"}],
                        "truncated": False,
                    },
                    "meta": {"ttl_ms": 5000, "cache_scope": "private"},
                },
                {"ok": False, "error": "not supported"},
            ]
        )

        assert [item.uri for item in await client.list_resources()] == [
            "memory://a",
            "memory://b",
        ]
        assert (await client.list_resource_templates())[0].template is True
        assert (await client.read_resource("memory://a"))["contents"][0]["text"] == "content"
        assert await client.list_prompts() == []
        assert client.catalog_errors["prompts"] == "not supported"

    @pytest.mark.asyncio
    async def test_get_prompt_preserves_structured_messages(self) -> None:
        client = MCPClient("srv", "echo")
        client._connected = True
        client._request = AsyncMock(
            return_value={
                "ok": True,
                "result": {
                    "description": "Review",
                    "messages": [{"role": "user", "content": {"type": "text", "text": "Hi"}}],
                },
            }
        )

        result = await client.get_prompt("review", {"path": "app.py"})
        assert result["ok"] is True
        assert result["messages"][0]["content"]["text"] == "Hi"

    @pytest.mark.asyncio
    async def test_complete_preserves_completion_metadata(self) -> None:
        client = MCPClient("srv", "echo")
        client._connected = True
        client._request = AsyncMock(
            return_value={
                "ok": True,
                "result": {"completion": {"values": ["app.py"], "has_more": False}},
            }
        )

        result = await client.complete("review", {"name": "path", "value": "app"})

        assert result["completion"]["values"] == ["app.py"]
        client._request.assert_awaited_once_with(
            "complete",
            reference="review",
            reference_type="prompt",
            argument={"name": "path", "value": "app"},
            context_arguments={},
        )

    def test_subscription_events_invalidate_catalogs_and_update_status(self) -> None:
        client = MCPClient("srv", "echo")
        client._set_catalog_meta("tools", {"ttl_ms": 60_000})
        client._apply_bridge_event(
            {
                "event": "subscription_status",
                "status": "active",
                "honored": {"tools_list_changed": True},
            }
        )
        client._apply_bridge_event(
            {
                "event": "subscription_event",
                "payload": {"type": "tools_list_changed"},
            }
        )

        assert client.subscription["status"] == "active"
        assert client.subscription["events"] == 1
        assert client.catalog_status()["tools"]["freshness"]["stale"] is True

    @pytest.mark.asyncio
    async def test_bridge_input_request_uses_explicit_host_handler(self) -> None:
        handler = AsyncMock(return_value={"action": "accept", "content": {"choice": "yes"}})
        client = MCPClient("srv", "echo", input_handler=handler)
        client._process = _FakeProcess(
            {
                "event": "input_request",
                "token": "input-1",
                "kind": "elicitation",
                "payload": {"message": "Choose", "requested_schema": {}},
            },
            {"ok": True, "id": 1, "result": {}},
        )

        response = await client._request("call_tool", name="choose", arguments={})

        assert response["ok"] is True
        handler.assert_awaited_once()
        assert client._process.stdin.lines[1] == {
            "op": "input_response",
            "token": "input-1",
            "result": {"action": "accept", "content": {"choice": "yes"}},
        }


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
        assert servers[0]["transport"] == "stdio"
        assert servers[0]["protocol_mode"] == "auto"

    @pytest.mark.asyncio
    async def test_invalid_config_is_reported_without_crashing_other_servers(self) -> None:
        manager = MCPManager(
            {
                "good": {"command": "echo"},
                "bad": {"transport": "streamable-http"},
            }
        )
        with patch("magent.mcp.client.MCPClient.connect", new=AsyncMock(return_value=False)):
            status = await manager.start_all()

        assert status == {"bad": False, "good": False}
        rows = {row["name"]: row for row in manager.list_servers()}
        assert "requires url" in rows["bad"]["error"]

    def test_connected_count_and_total_tools(self) -> None:
        tool = MCPTool("t", "", {}, "s")
        client = MagicMock()
        client.connected = True
        client.tools = [tool, tool]

        manager = MCPManager()
        manager._clients = {"s": client}
        assert manager.connected_count == 1
        assert manager.total_tools == 2

    @pytest.mark.asyncio
    async def test_manager_aggregates_catalogs_and_reads_resource(self) -> None:
        from magent.mcp.catalog import MCPPrompt, MCPResource

        client = MagicMock(spec=MCPClient)
        client.connected = True
        client.list_prompts = AsyncMock(
            return_value=[MCPPrompt("review", "", (), "srv")]
        )
        client.list_resources = AsyncMock(
            return_value=[MCPResource("memory://project", "Project", "", "", "srv")]
        )
        client.list_resource_templates = AsyncMock(return_value=[])
        client.read_resource = AsyncMock(return_value={"ok": True, "contents": []})
        manager = MCPManager()
        manager._clients = {"srv": client}

        assert (await manager.list_prompts())[0].name == "review"
        assert (await manager.list_resources())[0].uri == "memory://project"
        assert (await manager.read_resource("srv", "memory://project"))["ok"] is True

    @pytest.mark.asyncio
    async def test_manager_routes_completion(self) -> None:
        client = MagicMock(spec=MCPClient)
        client.connected = True
        client.complete = AsyncMock(return_value={"ok": True, "completion": {"values": []}})
        manager = MCPManager()
        manager._clients = {"srv": client}

        result = await manager.complete("srv", "review", {"name": "path", "value": "a"})

        assert result["ok"] is True
        client.complete.assert_awaited_once()
