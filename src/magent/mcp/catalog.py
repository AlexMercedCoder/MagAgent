"""Typed MCP prompt/resource catalogs and cache-freshness metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class MCPPrompt:
    name: str
    description: str
    arguments: tuple[dict[str, Any], ...]
    server_name: str

    @classmethod
    def from_payload(cls, value: dict[str, Any], server_name: str) -> MCPPrompt:
        arguments = value.get("arguments") or []
        return cls(
            name=str(value.get("name") or ""),
            description=str(value.get("description") or ""),
            arguments=tuple(item for item in arguments if isinstance(item, dict)),
            server_name=server_name,
        )


@dataclass(frozen=True, slots=True)
class MCPResource:
    uri: str
    name: str
    description: str
    mime_type: str
    server_name: str
    template: bool = False

    @classmethod
    def from_payload(
        cls, value: dict[str, Any], server_name: str, *, template: bool = False
    ) -> MCPResource:
        return cls(
            uri=str(value.get("uri_template" if template else "uri") or ""),
            name=str(value.get("name") or ""),
            description=str(value.get("description") or ""),
            mime_type=str(value.get("mime_type") or value.get("mimeType") or ""),
            server_name=server_name,
            template=template,
        )


@dataclass(slots=True)
class MCPCatalogFreshness:
    fetched_at: datetime
    ttl_ms: int
    cache_scope: str
    next_cursor: str | None = None
    stale: bool = False
    stale_reason: str = ""

    @classmethod
    def from_payload(cls, value: Any) -> MCPCatalogFreshness:
        payload = value if isinstance(value, dict) else {}
        raw_time = str(payload.get("fetched_at") or "")
        try:
            fetched_at = datetime.fromisoformat(raw_time).astimezone(UTC)
        except ValueError:
            fetched_at = datetime.now(UTC)
        return cls(
            fetched_at=fetched_at,
            ttl_ms=max(0, int(payload.get("ttl_ms") or 0)),
            cache_scope=str(payload.get("cache_scope") or "private"),
            next_cursor=str(payload["next_cursor"]) if payload.get("next_cursor") else None,
        )

    @property
    def expires_at(self) -> datetime:
        return self.fetched_at + timedelta(milliseconds=self.ttl_ms)

    @property
    def fresh(self) -> bool:
        return not self.stale and self.ttl_ms > 0 and datetime.now(UTC) < self.expires_at

    def invalidate(self, reason: str) -> None:
        self.stale = True
        self.stale_reason = reason

    def public_summary(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "ttl_ms": self.ttl_ms,
            "cache_scope": self.cache_scope,
            "fresh": self.fresh,
            "stale": self.stale,
            "stale_reason": self.stale_reason,
            "next_cursor": self.next_cursor,
        }
