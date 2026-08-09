"""MCP catalog adaptation and freshness tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from magent.mcp.catalog import MCPCatalogFreshness, MCPPrompt, MCPResource


def test_prompt_and_resources_adapt_sdk_payloads() -> None:
    prompt = MCPPrompt.from_payload(
        {"name": "review", "description": "Review", "arguments": [{"name": "path"}]},
        "server",
    )
    resource = MCPResource.from_payload(
        {"uri": "memory://project", "name": "Memory", "mime_type": "text/markdown"},
        "server",
    )
    template = MCPResource.from_payload(
        {"uri_template": "memory://{name}", "name": "Item"},
        "server",
        template=True,
    )

    assert prompt.arguments == ({"name": "path"},)
    assert resource.mime_type == "text/markdown"
    assert template.template is True
    assert template.uri == "memory://{name}"


def test_freshness_expires_and_can_be_invalidated() -> None:
    current = MCPCatalogFreshness.from_payload(
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "ttl_ms": 60_000,
            "cache_scope": "private",
        }
    )
    expired = MCPCatalogFreshness(
        fetched_at=datetime.now(UTC) - timedelta(seconds=2),
        ttl_ms=1,
        cache_scope="private",
    )

    assert current.fresh is True
    assert expired.fresh is False
    current.invalidate("tool-call:update")
    assert current.public_summary()["stale_reason"] == "tool-call:update"
    assert current.fresh is False


def test_invalid_timestamp_falls_back_safely() -> None:
    freshness = MCPCatalogFreshness.from_payload({"fetched_at": "not-a-date", "ttl_ms": -1})
    assert freshness.ttl_ms == 0
    assert freshness.fresh is False
