"""Skills system: discovery, parsing, matching, injection, and lockfile support."""

from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from magent.config import CONFIG_DIR, SKILLS_DIR, SKILLS_LOCK

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
        msg_lower = user_message.lower()
        score = 0.0

        if self._trigger_keywords:
            hits = sum(1 for kw in self._trigger_keywords if kw.lower() in msg_lower)
            score += hits / len(self._trigger_keywords)

        desc_words = set(re.sub(r"[^\w\s]", " ", self.description.lower()).split())
        msg_words = set(re.sub(r"[^\w\s]", " ", msg_lower).split())
        if desc_words:
            overlap = len(desc_words & msg_words) / len(desc_words)
            score += overlap * 0.5

        return min(score, 1.0)

    def to_context_block(self) -> str:
        return f"## Skill: {self.name}\n\n**Description:** {self.description}\n\n{self.body}\n"

    def to_lock_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "path": str(self.path),
            "description": self.description[:120],
        }


def parse_skill_file(path: Path) -> Skill | None:
    """Parse a SKILL.md file into a Skill object."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    frontmatter: dict[str, Any] = {}
    body = content

    fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if fm_match:
        with contextlib.suppress(Exception):
            frontmatter = yaml.safe_load(fm_match.group(1)) or {}
        body = fm_match.group(2).strip()

    name = frontmatter.get("name") or path.stem
    description = frontmatter.get("description", "")
    if isinstance(description, dict):
        description = str(description)
    version = str(frontmatter.get("version", "1.0"))
    tools_required = frontmatter.get("tools_required", [])

    trigger_keywords: list[str] = frontmatter.get("trigger_keywords", [])
    activate_match = re.search(
        r"##\s+When to Activate\n+(.*?)(?=\n##|\Z)", body, re.DOTALL | re.IGNORECASE
    )
    if activate_match:
        activate_text = activate_match.group(1)
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

    def load(self, respect_lockfile: bool = True) -> int:
        """
        Scan all skill directories and load SKILL.md files.
        If a skills.lock exists and respect_lockfile=True, only load locked skills.
        Returns count loaded.
        """
        self.skills = []
        locked_paths: set[str] | None = None

        if respect_lockfile and SKILLS_LOCK.exists():
            try:
                lock_data = json.loads(SKILLS_LOCK.read_text())
                locked_paths = {entry["path"] for entry in lock_data.get("skills", [])}
            except Exception:
                locked_paths = None

        for skill_dir in self._search_dirs:
            if not skill_dir.exists():
                continue
            for skill_md in skill_dir.rglob("SKILL.md"):
                if locked_paths is not None and str(skill_md) not in locked_paths:
                    continue
                skill = parse_skill_file(skill_md)
                if skill:
                    self.skills.append(skill)

        return len(self.skills)

    def save_lockfile(self) -> None:
        """Write skills.lock with all currently loaded skills."""
        lock_data = {
            "version": 1,
            "skills": [s.to_lock_entry() for s in self.skills],
        }
        SKILLS_LOCK.parent.mkdir(parents=True, exist_ok=True)
        SKILLS_LOCK.write_text(json.dumps(lock_data, indent=2))

    def match(self, user_message: str, max_skills: int = MAX_ACTIVE_SKILLS) -> list[Skill]:
        if not self.skills:
            return []
        scored = [(s.score_relevance(user_message), s) for s in self.skills]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for score, s in scored[:max_skills] if score > 0.05]

    def build_skill_context(self, user_message: str) -> str:
        active = self.match(user_message)
        if not active:
            return ""
        blocks = [s.to_context_block() for s in active]
        return "# Active Skills\n\n" + "\n---\n\n".join(blocks)

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
