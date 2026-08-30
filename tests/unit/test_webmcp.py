from pathlib import Path

import pytest

from magent.browser import _require_alexmerced_url
from magent.skills import SkillRegistry, parse_skill_file


def test_webmcp_skill_is_bundled_and_uses_declared_tools() -> None:
    registry = SkillRegistry()
    registry.load(respect_lockfile=False)

    matches = registry.match("Use WebMCP to merge this PDF with alexmerced.app")
    skill = next(item for item in matches if item.name == "alexmerced-webmcp")

    assert skill.tools_required == [
        "webmcp_open",
        "webmcp_list_tools",
        "webmcp_call_tool",
    ]


def test_skill_parser_accepts_agent_skills_hyphenated_metadata(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text(
        "---\nname: demo\ndescription: Demo\n"
        "tools-required: read_file\ntrigger-keywords: [demo]\n---\nBody\n",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_file)

    assert skill is not None
    assert skill.tools_required == ["read_file"]
    assert skill.score_relevance("demo") > 0


def test_browser_webmcp_origin_guard() -> None:
    assert _require_alexmerced_url("https://alexmerced.app/quire") == (
        "https://alexmerced.app/quire"
    )
    with pytest.raises(ValueError, match="restricted"):
        _require_alexmerced_url("https://example.com/")
