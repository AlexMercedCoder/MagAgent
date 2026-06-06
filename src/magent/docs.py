"""Packaged self-documentation for MagAgent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocTopic:
    slug: str
    title: str
    path: str


def docs_root() -> Path:
    return Path(str(resources.files("magent") / "docs"))


def list_topics() -> list[DocTopic]:
    root = docs_root()
    topics = []
    for path in sorted(root.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        title = _title_from_markdown(text) or path.stem.replace("-", " ").title()
        topics.append(DocTopic(slug=path.stem, title=title, path=str(path)))
    return topics


def read_topic(slug: str) -> str:
    path = _resolve_topic_path(slug)
    if not path:
        raise KeyError(slug)
    return path.read_text(encoding="utf-8", errors="replace")


def search_docs(query: str, limit: int = 8) -> list[dict[str, Any]]:
    terms = set(_terms(query))
    if not terms:
        return []
    results = []
    for topic in list_topics():
        text = read_topic(topic.slug)
        body_terms = set(_terms(text))
        title_terms = set(_terms(topic.title + " " + topic.slug))
        score = len(terms & body_terms) + (len(terms & title_terms) * 2)
        if score:
            results.append(
                {
                    "slug": topic.slug,
                    "title": topic.title,
                    "score": score,
                    "snippet": _snippet(text, terms),
                }
            )
    results.sort(key=lambda item: (item["score"], item["title"]), reverse=True)
    return results[:limit]


def docs_doctor(command_names: list[str] | None = None) -> dict[str, Any]:
    topics = list_topics()
    slugs = {topic.slug for topic in topics}
    required = {
        "overview",
        "commands",
        "memory",
        "semantic-memory",
        "workbench",
        "checkpoints",
        "configuration",
        "troubleshooting",
    }
    missing_topics = sorted(required - slugs)
    docs_text = "\n".join(read_topic(topic.slug) for topic in topics)
    missing_commands = []
    if command_names:
        missing_commands = [
            name for name in sorted(set(command_names)) if f"magent {name}" not in docs_text
        ]
    return {
        "ok": not missing_topics and not missing_commands,
        "topics": len(topics),
        "missing_topics": missing_topics,
        "missing_commands": missing_commands,
    }


def _resolve_topic_path(slug: str) -> Path | None:
    root = docs_root()
    normalized = slug.strip().lower().replace("_", "-")
    candidates = [root / f"{normalized}.md"]
    for topic in list_topics():
        if normalized in {topic.slug, topic.title.lower().replace(" ", "-")}:
            candidates.append(Path(topic.path))
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _title_from_markdown(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _terms(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]{2,}", text.lower())


def _snippet(text: str, terms: set[str]) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        lower = line.lower()
        if any(term in lower for term in terms):
            return line[:220]
    return (lines[0] if lines else "")[:220]
