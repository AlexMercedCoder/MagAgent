"""Typed MCP server configuration and protocol compatibility metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class MCPConfigError(ValueError):
    """Raised when an MCP server configuration cannot be normalized safely."""


class MCPProtocolMode(StrEnum):
    """Protocol era preference for one configured server."""

    AUTO = "auto"
    MODERN = "modern"
    LEGACY = "legacy"


class MCPTransport(StrEnum):
    """Supported and planned MCP transport identifiers."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"
    LEGACY_SSE = "legacy-sse"


_TRANSPORT_ALIASES = {
    "stdio": MCPTransport.STDIO,
    "http": MCPTransport.STREAMABLE_HTTP,
    "streamable-http": MCPTransport.STREAMABLE_HTTP,
    "streamable_http": MCPTransport.STREAMABLE_HTTP,
    "sse": MCPTransport.LEGACY_SSE,
    "legacy-sse": MCPTransport.LEGACY_SSE,
    "legacy_sse": MCPTransport.LEGACY_SSE,
}


@dataclass(frozen=True, slots=True)
class MCPServerProfile:
    """Normalized configuration independent of a particular MCP SDK version."""

    name: str
    transport: MCPTransport
    protocol_mode: MCPProtocolMode
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str = ""
    headers: dict[str, str] | None = None
    timeout: float = 30.0
    allow_deprecated_transport: bool = False

    @classmethod
    def from_config(cls, name: str, config: dict[str, Any]) -> MCPServerProfile:
        """Validate and normalize one ``[mcp.servers.<name>]`` table."""
        if not isinstance(config, dict):
            raise MCPConfigError(f"MCP server '{name}' must be a table/object")

        command = str(config.get("command") or "").strip()
        url = str(config.get("url") or "").strip()
        raw_transport = str(config.get("transport") or ("streamable-http" if url else "stdio"))
        transport = _TRANSPORT_ALIASES.get(raw_transport.strip().lower())
        if transport is None:
            valid = ", ".join(item.value for item in MCPTransport)
            raise MCPConfigError(f"MCP server '{name}' has unknown transport '{raw_transport}'; use {valid}")

        raw_mode = str(config.get("protocol_mode") or "auto").strip().lower()
        try:
            protocol_mode = MCPProtocolMode(raw_mode)
        except ValueError as exc:
            raise MCPConfigError(
                f"MCP server '{name}' has unknown protocol_mode '{raw_mode}'; use auto, modern, or legacy"
            ) from exc

        if transport is MCPTransport.STDIO and not command:
            raise MCPConfigError(f"MCP stdio server '{name}' requires command")
        if transport is not MCPTransport.STDIO and not url:
            raise MCPConfigError(f"MCP {transport.value} server '{name}' requires url")

        allow_deprecated = bool(config.get("allow_deprecated_transport", False))
        if transport is MCPTransport.LEGACY_SSE and not allow_deprecated:
            raise MCPConfigError(
                f"MCP server '{name}' uses deprecated legacy-sse; set allow_deprecated_transport=true explicitly"
            )

        args = config.get("args") or []
        env = config.get("env")
        headers = config.get("headers")
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise MCPConfigError(f"MCP server '{name}' args must be a list of strings")
        if env is not None and (
            not isinstance(env, dict)
            or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items())
        ):
            raise MCPConfigError(f"MCP server '{name}' env must contain string keys and values")
        if headers is not None and (
            not isinstance(headers, dict)
            or not all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items())
        ):
            raise MCPConfigError(f"MCP server '{name}' headers must contain string keys and values")

        try:
            timeout = float(config.get("timeout", 30.0))
        except (TypeError, ValueError) as exc:
            raise MCPConfigError(f"MCP server '{name}' timeout must be numeric") from exc
        if timeout <= 0:
            raise MCPConfigError(f"MCP server '{name}' timeout must be greater than zero")

        return cls(
            name=name,
            transport=transport,
            protocol_mode=protocol_mode,
            command=command,
            args=tuple(args),
            env=dict(env) if env is not None else None,
            cwd=str(config.get("cwd")) if config.get("cwd") else None,
            url=url,
            headers=dict(headers) if headers is not None else None,
            timeout=timeout,
            allow_deprecated_transport=allow_deprecated,
        )

    @property
    def endpoint(self) -> str:
        """Human-readable endpoint with no environment or authentication values."""
        if self.transport is MCPTransport.STDIO:
            return " ".join((self.command, *self.args)).strip()
        return self.url

    @property
    def public_endpoint(self) -> str:
        """Identify the endpoint without exposing arguments, credentials, or queries."""
        if self.transport is MCPTransport.STDIO:
            suffix = f" ({len(self.args)} args)" if self.args else ""
            return f"{self.command}{suffix}"
        parsed = urlsplit(self.url)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))

    def public_summary(self) -> dict[str, Any]:
        """Return diagnostics metadata that cannot expose headers or environment secrets."""
        return {
            "name": self.name,
            "transport": self.transport.value,
            "protocol_mode": self.protocol_mode.value,
            "endpoint": self.public_endpoint,
            "timeout": self.timeout,
            "deprecated_transport": self.transport is MCPTransport.LEGACY_SSE,
        }


def normalize_mcp_servers(config: Any) -> tuple[dict[str, MCPServerProfile], dict[str, str]]:
    """Normalize a server map while retaining an actionable error for each bad entry."""
    if not isinstance(config, dict):
        return {}, {"mcp.servers": "MCP servers must be a table/object"}
    profiles: dict[str, MCPServerProfile] = {}
    errors: dict[str, str] = {}
    for raw_name, raw_config in config.items():
        name = str(raw_name)
        try:
            profiles[name] = MCPServerProfile.from_config(name, raw_config)
        except MCPConfigError as exc:
            errors[name] = str(exc)
    return profiles, errors
