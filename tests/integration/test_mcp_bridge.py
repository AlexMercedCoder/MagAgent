"""Optional real-process interoperability checks for the MCP SDK v2 bridge."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

from magent.mcp.client import MCPClient


def _has_sdk_v2() -> bool:
    if importlib.util.find_spec("mcp") is None:
        return False
    try:
        return int(version("mcp").split(".", maxsplit=1)[0]) == 2
    except (PackageNotFoundError, ValueError):
        return False


pytestmark = pytest.mark.skipif(not _has_sdk_v2(), reason="MCP SDK v2 optional extra not installed")


async def _wait_for_wire_count(client: MCPClient, marker: str, minimum: int) -> int:
    """Let the independent stderr drain observe a completed wire request."""
    for _ in range(100):
        count = client._stderr_tail.count(marker)
        if count >= minimum:
            return count
        await asyncio.sleep(0.01)
    return client._stderr_tail.count(marker)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "era", "revision"),
    [
        ("modern", "modern", "2026-07-28"),
        ("legacy", "legacy", "2025-11-25"),
        ("auto", "modern", "2026-07-28"),
    ],
)
async def test_bridge_negotiates_and_calls_tool(mode: str, era: str, revision: str) -> None:
    server = Path(__file__).parents[1] / "fixtures" / "mcp_dual_server.py"
    input_requests: list[dict[str, object]] = []

    async def handle_input(request: dict[str, object]) -> dict[str, object]:
        input_requests.append(request)
        return {"action": "accept", "content": {"channel": "stable"}}

    client = MCPClient(
        "fixture",
        sys.executable,
        [str(server)],
        protocol_mode=mode,
        timeout=5,
        input_handler=handle_input,
    )

    try:
        assert await client.connect()
        assert client.selected_era == era
        assert client.selected_protocol_version == revision
        assert [tool.name for tool in client.tools] == ["choose", "echo"]
        tool_result = await client.call_tool("echo", {"message": mode})
        assert tool_result["ok"] is True
        assert tool_result["result"] == mode
        assert tool_result["structured_content"] == {"message": mode}
        assert tool_result["content"] == [{"type": "text", "text": mode}]
        prompts = await client.list_prompts()
        prompt_marker = "wire fixture received prompts/list"
        prompt_requests = await _wait_for_wire_count(client, prompt_marker, 1)
        prompt_is_fresh = client.catalog_status()["prompts"]["freshness"]["fresh"]
        assert await client.list_prompts() == prompts
        expected_cached_requests = prompt_requests + (0 if prompt_is_fresh else 1)
        cached_prompt_requests = await _wait_for_wire_count(
            client, prompt_marker, expected_cached_requests
        )
        assert cached_prompt_requests == expected_cached_requests
        resources = await client.list_resources()
        templates = await client.list_resource_templates()
        assert [item.name for item in prompts] == ["review"]
        assert [item.uri for item in resources] == ["memory://project"]
        assert [item.uri for item in templates] == ["memory://item/{name}"]
        assert (await client.get_prompt("review", {"path": "app.py"}))["messages"][0]["content"][
            "text"
        ] == "Review app.py"
        completion = await client.complete("review", {"name": "path", "value": "app"})
        assert completion["completion"]["values"] == ["app.py"]
        if era == "modern":
            elicited = await client.call_tool("choose", {})
            assert elicited["result"] == "stable"
            assert input_requests[0]["kind"] == "elicitation"
        resource = await client.read_resource("memory://project")
        resource_requests = await _wait_for_wire_count(
            client, "wire fixture received resources/read", 1
        )
        assert resource["contents"][0]["text"].startswith("# Project")
        if era == "modern":
            assert resource["cache"]["ttl_ms"] == 60_000
        else:
            # Cache directives are a 2026-era field. SDK 2.0 retained the
            # extension on legacy responses; SDK 2.1 correctly normalizes it
            # away. MagAgent supports both dependency versions.
            assert resource["cache"]["ttl_ms"] in {0, 60_000}
        await client.call_tool("echo", {"message": "invalidate"})
        assert client.catalog_status()["prompts"]["freshness"]["stale"] is True
        await client.list_prompts()
        assert await _wait_for_wire_count(client, prompt_marker, cached_prompt_requests + 1) == (
            cached_prompt_requests + 1
        )
        await client.read_resource("memory://project")
        assert (
            await _wait_for_wire_count(
                client, "wire fixture received resources/read", resource_requests + 1
            )
            == resource_requests + 1
        )
    finally:
        await client.disconnect()
