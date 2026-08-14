"""Typed boundaries between requested, resolved, and effective profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Adjustment:
    field: str
    requested: Any
    effective: Any
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "requested": self.requested,
            "effective": self.effective,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResolvedProfile:
    document: dict[str, Any]
    source_path: Path | None
    trust: str
    spec_digest: str
    profile_digest: str
    encoding: str = "yaml"
    legacy: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return str(self.document.get("metadata", {}).get("name", ""))

    @property
    def revision(self) -> int:
        return int(self.document.get("metadata", {}).get("revision", 1))

    def as_dict(self, *, include_document: bool = True) -> dict[str, Any]:
        item = {
            "name": self.name,
            "revision": self.revision,
            "source": str(self.source_path) if self.source_path else "managed",
            "trust": self.trust,
            "encoding": self.encoding,
            "legacy": self.legacy,
            "spec_digest": self.spec_digest,
            "profile_digest": self.profile_digest,
            "warnings": list(self.warnings),
        }
        if include_document:
            item["document"] = self.document
        return item


@dataclass(frozen=True)
class EffectiveProfile:
    resolved: ResolvedProfile
    tools: frozenset[str]
    permission_mode: str
    provider: str = ""
    model: str = ""
    max_turns: int = 0
    max_state_tokens: int = 0
    writeback: str = "off"
    tool_budgets: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    session_usd: float = 0.0
    adjustments: tuple[Adjustment, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        return self.resolved.name

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.resolved.as_dict(include_document=False),
            "tools": sorted(self.tools),
            "permission_mode": self.permission_mode,
            "provider": self.provider,
            "model": self.model,
            "max_turns": self.max_turns,
            "max_state_tokens": self.max_state_tokens,
            "writeback": self.writeback,
            "tool_budgets": dict(self.tool_budgets),
            "session_usd": self.session_usd,
            "adjustments": [item.as_dict() for item in self.adjustments],
        }
