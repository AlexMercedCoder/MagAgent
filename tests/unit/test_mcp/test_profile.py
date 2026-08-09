"""MCP dual-era configuration boundary tests."""

from __future__ import annotations

import pytest

from magent.mcp.profile import (
    MCPConfigError,
    MCPProtocolMode,
    MCPServerProfile,
    MCPTransport,
    normalize_mcp_servers,
)


def test_classic_stdio_config_normalizes_without_new_fields() -> None:
    profile = MCPServerProfile.from_config(
        "files",
        {"command": "npx", "args": ["-y", "server"], "env": {"TOKEN": "secret"}},
    )

    assert profile.transport is MCPTransport.STDIO
    assert profile.protocol_mode is MCPProtocolMode.AUTO
    assert profile.endpoint == "npx -y server"
    assert profile.public_summary()["endpoint"] == "npx (2 args)"
    assert "secret" not in str(profile.public_summary())


def test_modern_http_config_is_recognized_for_future_adapter() -> None:
    profile = MCPServerProfile.from_config(
        "remote",
        {
            "transport": "streamable_http",
            "protocol_mode": "modern",
            "url": "https://mcp.example.test/api",
            "headers": {"Authorization": "Bearer secret"},
        },
    )

    assert profile.transport is MCPTransport.STREAMABLE_HTTP
    assert profile.protocol_mode is MCPProtocolMode.MODERN
    assert profile.endpoint == "https://mcp.example.test/api"
    assert "Bearer" not in str(profile.public_summary())


def test_public_endpoints_remove_argument_and_url_credentials() -> None:
    local = MCPServerProfile.from_config(
        "db",
        {"command": "db-server", "args": ["postgres://user:secret@localhost/db"]},
    )
    remote = MCPServerProfile.from_config(
        "remote",
        {"url": "https://user:secret@example.test/mcp?token=secret"},
    )

    assert "secret" not in local.public_endpoint
    assert remote.public_endpoint == "https://example.test/mcp"


@pytest.mark.parametrize("mode", ["future", "2026-07-28", "classic"])
def test_unknown_protocol_mode_is_rejected(mode: str) -> None:
    with pytest.raises(MCPConfigError, match="protocol_mode"):
        MCPServerProfile.from_config("bad", {"command": "echo", "protocol_mode": mode})


def test_deprecated_sse_requires_explicit_opt_in() -> None:
    with pytest.raises(MCPConfigError, match="allow_deprecated_transport"):
        MCPServerProfile.from_config(
            "old",
            {"transport": "sse", "url": "https://example.test/sse"},
        )


def test_invalid_entries_do_not_hide_valid_servers() -> None:
    profiles, errors = normalize_mcp_servers(
        {
            "good": {"command": "echo"},
            "bad": {"transport": "streamable-http"},
        }
    )

    assert list(profiles) == ["good"]
    assert "requires url" in errors["bad"]


def test_timeout_and_string_collections_are_validated() -> None:
    with pytest.raises(MCPConfigError, match="args"):
        MCPServerProfile.from_config("bad", {"command": "echo", "args": "--version"})
    with pytest.raises(MCPConfigError, match="greater than zero"):
        MCPServerProfile.from_config("bad", {"command": "echo", "timeout": 0})
