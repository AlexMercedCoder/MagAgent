"""Typed record helpers for common MagAgent dict payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskRecord:
    id: str = ""
    title: str = ""
    status: str = "open"
    project: str = ""
    priority: str = "normal"

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> TaskRecord:
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            status=str(data.get("status", "open")),
            project=str(data.get("project", "")),
            priority=str(data.get("priority", "normal")),
        )


@dataclass(frozen=True)
class PlanRecord:
    id: str = ""
    goal: str = ""
    status: str = "draft"
    project: str = ""
    root: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> PlanRecord:
        return cls(
            id=str(data.get("id", "")),
            goal=str(data.get("goal", "")),
            status=str(data.get("status", "draft")),
            project=str(data.get("project", "")),
            root=str(data.get("root", "")),
        )


@dataclass(frozen=True)
class PromotionCandidateRecord:
    id: str
    source: str
    source_id: str
    title: str
    type: str
    body: str
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> PromotionCandidateRecord:
        return cls(
            id=str(data.get("id", "")),
            source=str(data.get("source", "")),
            source_id=str(data.get("source_id", "")),
            title=str(data.get("title", "")),
            type=str(data.get("type", "fact")),
            body=str(data.get("body", "")),
            tags=[str(item) for item in data.get("tags", [])],
            links=[str(item) for item in data.get("links", [])],
        )

    def to_memory_item(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "body": self.body,
            "tags": list(self.tags),
            "links": list(self.links),
        }
