"""Tests for token-efficiency helpers."""

from pathlib import Path

from magent.memory import MemoryManager
from magent.repo_map import RepoMapCache
from magent.skills import Skill, SkillRegistry
from magent.tokens import estimate_tokens, truncate_to_tokens


def test_truncate_to_tokens_adds_marker() -> None:
    text = "x" * 200
    shortened = truncate_to_tokens(text, 10, "[cut]")
    assert len(shortened) < len(text)
    assert shortened.endswith("[cut]")
    assert estimate_tokens(shortened) <= 12


def test_repo_map_returns_relevant_symbols(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text(
        "class AuthService:\n"
        "    def login(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    repo_map = RepoMapCache(tmp_path)
    rendered = repo_map.relevant_slice("login auth service", max_tokens=200)

    assert "auth.py" in rendered
    assert "AuthService" in rendered
    assert "login" in rendered


def test_skill_context_respects_budget(tmp_path: Path) -> None:
    registry = SkillRegistry()
    registry.skills = [
        Skill(
            name="big",
            description="python testing",
            body="pytest " * 1000,
            path=tmp_path / "SKILL.md",
            trigger_keywords=["pytest"],
        )
    ]

    context = registry.build_skill_context("please use pytest", budget_tokens=80)

    assert "Skill: big" in context
    assert "[...skill truncated for budget...]" in context
    assert estimate_tokens(context) <= 110


def test_memory_recall_reports_budget(tmp_path: Path) -> None:
    (tmp_path / "prefers_pytest.md").write_text(
        '---\nid: "prefers_pytest"\ntype: "preference"\nlinks: []\n---\n'
        "# Prefers Pytest\n\n" + ("User prefers pytest. " * 100),
        encoding="utf-8",
    )

    mgr = MemoryManager(tmp_path, budget_tokens=80, max_node_tokens=30)
    recalled = mgr.recall("pytest")

    assert "Budget: ~80 tokens" in recalled
    assert mgr.last_recall_stats["nodes"] == 1
    assert mgr.last_recall_stats["tokens"] <= 90
