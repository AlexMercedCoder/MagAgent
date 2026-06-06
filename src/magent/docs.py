"""Packaged self-documentation for MagAgent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
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
    return list(_cached_topics())


@lru_cache(maxsize=1)
def _cached_topics() -> tuple[DocTopic, ...]:
    root = docs_root()
    topics = []
    for path in sorted(root.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        title = _title_from_markdown(text) or path.stem.replace("-", " ").title()
        topics.append(DocTopic(slug=path.stem, title=title, path=str(path)))
    return tuple(topics)


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
        "architecture",
        "commands",
        "memory",
        "semantic-memory",
        "workbench",
        "checkpoints",
        "configuration",
        "troubleshooting",
        "recipes",
        "tutorial",
        "testing",
        "patch-workflow",
        "ui",
        "tui",
        "context",
        "playbooks",
        "tool-packs",
        "sandbox",
        "evals",
        "browser",
        "github",
        "comparisons",
        "providers",
        "config-reference",
        "performance",
        "agents",
        "hooks",
        "lsp",
        "daemon",
        "plugins",
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


def render_command_reference(command_names: list[str]) -> str:
    lines = [
        "# Generated Command Reference",
        "",
        "Generated from the active Typer command tree.",
        "",
    ]
    groups: dict[str, list[str]] = {"core": []}
    for name in sorted(set(command_names)):
        if " " in name:
            group, command = name.split(" ", 1)
            groups.setdefault(group, []).append(command)
        else:
            groups["core"].append(name)
    for group, commands in sorted(groups.items()):
        lines.extend([f"## {group}", ""])
        for command in sorted(commands):
            rendered = f"magent {command}" if group == "core" else f"magent {group} {command}"
            lines.append(f"- `{rendered}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_provider_reference() -> str:
    """Generate provider reference Markdown from the provider catalog."""
    from magent.provider_catalog import PROVIDER_CATALOG, PROVIDER_ORDER

    lines = [
        "# Provider Reference",
        "",
        "Generated from `magent.provider_catalog`.",
        "",
        "| Provider | ID | Default Model | Access | Env | Runtime |",
        "|---|---|---|---|---|---|",
    ]
    for provider_id in PROVIDER_ORDER:
        metadata = PROVIDER_CATALOG[provider_id]
        lines.append(
            "| "
            + " | ".join(
                [
                    metadata["display"],
                    f"`{provider_id}`",
                    f"`{metadata['default_model']}`",
                    metadata["access_mode"],
                    f"`{metadata.get('env', '')}`" if metadata.get("env") else "",
                    metadata["litellm"],
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Use `magent provider matrix`, `magent provider explain <provider>`, and `magent provider env` for live readiness details.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def render_config_reference() -> str:
    """Generate config reference Markdown from packaged defaults and catalogs."""
    from magent.config import DEFAULT_GLOBAL_CONFIG, DEFAULT_USER_PROFILE
    from magent.config_ux import MODEL_ROLES
    from magent.permission_ux import PERMISSION_MODES
    from magent.provider_catalog import PROVIDER_ORDER

    lines = [
        "# Config Reference",
        "",
        "Generated from MagAgent's packaged default config and provider metadata.",
        "",
        "## Global Config",
        "",
        "Stored at `~/.config/magent/config.toml`.",
        "",
    ]
    lines.extend(_render_config_tree(DEFAULT_GLOBAL_CONFIG))
    lines.extend(
        [
            "",
            "## User Profile",
            "",
            "Stored at `~/.config/magent/users/<user>/profile.toml`.",
            "",
        ]
    )
    lines.extend(_render_config_tree(DEFAULT_USER_PROFILE))
    lines.extend(
        [
            "",
            "## Model Roles",
            "",
            "Use `magent model set-role <role> <provider/model>` and `magent model health`.",
            "",
        ]
    )
    for role in MODEL_ROLES:
        lines.append(f"- `{role}`")
    lines.extend(
        [
            "",
            "## Permission Modes",
            "",
            "Use `magent permission explain <mode>` and `magent permission set <mode>`.",
            "",
        ]
    )
    for mode, description in sorted(PERMISSION_MODES.items()):
        lines.append(f"- `{mode}`: {description}")
    lines.extend(
        [
            "",
            "## Provider IDs",
            "",
            "Use `magent provider matrix` and `magent provider test-matrix` for live readiness.",
            "",
        ]
    )
    for provider_id in PROVIDER_ORDER:
        lines.append(f"- `{provider_id}`")
    return "\n".join(lines).strip() + "\n"


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


def _render_config_tree(data: dict[str, Any], prefix: str = "") -> list[str]:
    lines = []
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            lines.append(f"### `{path}`")
            lines.append("")
            lines.extend(_render_config_tree(value, path))
        else:
            rendered = repr(_display_default(value))
            lines.append(f"- `{path}` default: `{rendered}`")
    return lines


def _display_default(value: Any) -> Any:
    if isinstance(value, str):
        home = str(Path.home())
        if value.startswith(home):
            return "~" + value[len(home):]
    return value


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
