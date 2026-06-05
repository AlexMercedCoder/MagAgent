"""Skills system: discovery, parsing, matching, and injection."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from magent.config import CONFIG_DIR, SKILLS_DIR

console = Console()

MAX_ACTIVE_SKILLS = 3


class Skill:
    """A parsed SKILL.md file."""

    def __init__(
        self,
        name: str,
        description: str,
        body: str,
        path: Path,
        version: str = "1.0",
        tools_required: list[str] | None = None,
        trigger_keywords: list[str] | None = None,
    ):
        self.name = name
        self.description = description
        self.body = body
        self.path = path
        self.version = version
        self.tools_required = tools_required or []
        self._trigger_keywords = trigger_keywords or []

    def score_relevance(self, user_message: str) -> float:
        """
        Return a relevance score [0, 1] for this skill vs the user's message.
        Higher = more relevant.
        """
        msg_lower = user_message.lower()
        score = 0.0

        # Check explicit trigger keywords
        if self._trigger_keywords:
            hits = sum(1 for kw in self._trigger_keywords if kw.lower() in msg_lower)
            score += hits / len(self._trigger_keywords)

        # Keyword match against description
        desc_words = set(re.sub(r"[^\w\s]", " ", self.description.lower()).split())
        msg_words = set(re.sub(r"[^\w\s]", " ", msg_lower).split())
        if desc_words:
            overlap = len(desc_words & msg_words) / len(desc_words)
            score += overlap * 0.5

        return min(score, 1.0)

    def to_context_block(self) -> str:
        """Format this skill for injection into system prompt."""
        return (
            f"## Skill: {self.name}\n\n"
            f"**Description:** {self.description}\n\n"
            f"{self.body}\n"
        )


def parse_skill_file(path: Path) -> Skill | None:
    """Parse a SKILL.md file into a Skill object."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    # Extract YAML frontmatter
    frontmatter: dict[str, Any] = {}
    body = content

    fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if fm_match:
        try:
            frontmatter = yaml.safe_load(fm_match.group(1)) or {}
        except Exception:
            pass
        body = fm_match.group(2).strip()

    name = frontmatter.get("name") or path.stem
    description = frontmatter.get("description", "")
    if isinstance(description, dict):
        description = str(description)
    version = str(frontmatter.get("version", "1.0"))
    tools_required = frontmatter.get("tools_required", [])

    # Extract trigger keywords from description and a "When to Activate" section
    trigger_keywords: list[str] = frontmatter.get("trigger_keywords", [])
    activate_match = re.search(
        r"##\s+When to Activate\n+(.*?)(?=\n##|\Z)", body, re.DOTALL | re.IGNORECASE
    )
    if activate_match:
        activate_text = activate_match.group(1)
        # Extract quoted words as keywords
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", activate_text)
        trigger_keywords.extend(quoted)

    return Skill(
        name=name,
        description=description,
        body=body,
        path=path,
        version=version,
        tools_required=tools_required,
        trigger_keywords=trigger_keywords,
    )


class SkillRegistry:
    """Discovers and manages available skills."""

    def __init__(self, extra_dirs: list[Path] | None = None):
        self.skills: list[Skill] = []
        self._search_dirs: list[Path] = [SKILLS_DIR]
        if extra_dirs:
            self._search_dirs.extend(extra_dirs)

    def load(self) -> int:
        """Scan all skill directories and load SKILL.md files. Returns count loaded."""
        self.skills = []
        for skill_dir in self._search_dirs:
            if not skill_dir.exists():
                continue
            for skill_md in skill_dir.rglob("SKILL.md"):
                skill = parse_skill_file(skill_md)
                if skill:
                    self.skills.append(skill)
        return len(self.skills)

    def match(self, user_message: str, max_skills: int = MAX_ACTIVE_SKILLS) -> list[Skill]:
        """Return up to max_skills skills most relevant to the user message."""
        if not self.skills:
            return []
        scored = [(s.score_relevance(user_message), s) for s in self.skills]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for score, s in scored[:max_skills] if score > 0.05]

    def build_skill_context(self, user_message: str) -> str:
        """Build skill injection block for system prompt."""
        active = self.match(user_message)
        if not active:
            return ""
        blocks = [s.to_context_block() for s in active]
        return (
            "# Active Skills\n\n"
            + "\n---\n\n".join(blocks)
        )

    def list_all(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description[:100],
                "version": s.version,
                "path": str(s.path),
            }
            for s in self.skills
        ]
