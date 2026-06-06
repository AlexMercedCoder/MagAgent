"""Project/user agent definitions and prompt invocation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from magent.config import CONFIG_DIR


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    prompt: str
    description: str = ""
    mode: str = "subagent"
    provider: str = ""
    model: str = ""
    tools: dict[str, Any] = field(default_factory=dict)
    permission_mode: str = ""
    memory_mode: str = ""
    max_turns: int = 0
    path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "tools": self.tools,
            "permission_mode": self.permission_mode,
            "memory_mode": self.memory_mode,
            "max_turns": self.max_turns,
            "path": self.path,
            "prompt": self.prompt,
        }


BUILTIN_AGENTS: dict[str, AgentDefinition] = {
    "review": AgentDefinition(
        name="review",
        mode="subagent",
        description="Read-only code review focused on correctness, security, and tests.",
        tools={"write": False, "edit": False, "delete": False},
        permission_mode="paranoid",
        prompt=(
            "You are MagAgent's review agent. Do not make edits unless explicitly asked. "
            "Prioritize bugs, regressions, security risks, and missing tests."
        ),
    ),
    "explore": AgentDefinition(
        name="explore",
        mode="subagent",
        description="Fast codebase exploration and context gathering.",
        tools={"read": True, "search": True, "shell": "ask"},
        max_turns=6,
        prompt=(
            "You are MagAgent's explore agent. Gather relevant files, commands, and context, "
            "then summarize the shortest useful path forward."
        ),
    ),
    "docs": AgentDefinition(
        name="docs",
        mode="subagent",
        description="Documentation writing and docs audit agent.",
        prompt=(
            "You are MagAgent's documentation agent. Keep docs accurate, concise, and aligned "
            "with the live CLI and architecture."
        ),
    ),
}


def agent_dirs(project: str | Path = ".") -> list[Path]:
    from magent.plugins import enabled_plugin_paths

    root = Path(project).resolve()
    return [
        CONFIG_DIR / "agents",
        root / ".magent" / "agents",
        *[plugin / "agents" for plugin in enabled_plugin_paths()],
    ]


def list_agents(project: str | Path = ".") -> dict[str, Any]:
    agents = dict(BUILTIN_AGENTS)
    for directory in agent_dirs(project):
        for path in sorted(directory.glob("*.md")) if directory.exists() else []:
            definition = load_agent_file(path)
            agents[definition.name] = definition
    return {"ok": True, "agents": [agent.as_dict() for agent in sorted(agents.values(), key=lambda item: item.name)]}


def get_agent(name: str, project: str | Path = ".") -> AgentDefinition | None:
    normalized = name.strip().lstrip("@").lower()
    agents = {item["name"]: item for item in list_agents(project)["agents"]}
    data = agents.get(normalized)
    return AgentDefinition(**data) if data else None


def load_agent_file(path: Path) -> AgentDefinition:
    text = path.read_text(encoding="utf-8", errors="replace")
    metadata, body = _split_frontmatter(text)
    return AgentDefinition(
        name=str(metadata.get("name") or path.stem).strip().lower(),
        description=str(metadata.get("description") or ""),
        mode=str(metadata.get("mode") or "subagent"),
        provider=str(metadata.get("provider") or ""),
        model=str(metadata.get("model") or ""),
        tools=metadata.get("tools") if isinstance(metadata.get("tools"), dict) else {},
        permission_mode=str(metadata.get("permissionMode") or metadata.get("permission_mode") or ""),
        memory_mode=str(metadata.get("memory") or metadata.get("memory_mode") or ""),
        max_turns=int(metadata.get("maxTurns") or metadata.get("max_turns") or 0),
        path=str(path),
        prompt=body.strip(),
    )


def create_agent(
    project: str | Path,
    name: str,
    *,
    description: str = "",
    mode: str = "subagent",
    prompt: str = "",
    force: bool = False,
) -> dict[str, Any]:
    directory = Path(project).resolve() / ".magent" / "agents"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name.strip().lower()}.md"
    if path.exists() and not force:
        return {"ok": False, "error": f"Agent already exists: {path}"}
    content = "\n".join(
        [
            "---",
            f"description: {description or name}",
            f"mode: {mode}",
            "tools: {}",
            "---",
            "",
            prompt or f"You are the {name} agent. Describe your specialty here.",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(path), "agent": load_agent_file(path).as_dict()}


def resolve_invocation(message: str, project: str | Path = ".") -> dict[str, Any]:
    stripped = message.strip()
    if not stripped.startswith("@"):
        return {"ok": False, "message": message}
    head, _, rest = stripped.partition(" ")
    agent = get_agent(head[1:], project)
    if not agent:
        return {"ok": False, "message": message, "error": f"Unknown agent: {head}"}
    prompt = "\n".join(
        [
            f"## Agent Invocation: @{agent.name}",
            "",
            agent.prompt,
            "",
            "## User Task",
            rest.strip() or "Use your specialty to help with the current project.",
        ]
    )
    return {"ok": True, "agent": agent.as_dict(), "message": prompt}


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    _, _, remainder = text.partition("---")
    frontmatter, sep, body = remainder.partition("---")
    if not sep:
        return {}, text
    try:
        data = yaml.safe_load(frontmatter) or {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}, body
