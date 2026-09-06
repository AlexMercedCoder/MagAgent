from pathlib import Path

import pytest

from magent.browser import (
    _require_alexmerced_url,
    normalize_webmcp_origins,
    require_webmcp_url,
    webmcp_invoke,
    webmcp_registry_revision,
)
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
        "webmcp_status",
        "webmcp_close",
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


def test_configured_webmcp_origins_are_exact_https_boundaries() -> None:
    origins = normalize_webmcp_origins(
        ["https://alexmerced.app/", "https://tools.example.com", "http://unsafe.test"]
    )
    assert origins == ("https://alexmerced.app", "https://tools.example.com")
    assert require_webmcp_url("https://tools.example.com/page", origins).endswith("/page")
    assert require_webmcp_url("https://tools.example.com:443/page", origins).endswith("/page")
    with pytest.raises(ValueError, match="configured HTTPS origins"):
        require_webmcp_url("https://sub.tools.example.com/page", origins)
    with pytest.raises(ValueError, match="at least one exact HTTPS origin"):
        normalize_webmcp_origins(["https://user:secret@tools.example.com"])
    with pytest.raises(ValueError, match="at least one exact HTTPS origin"):
        normalize_webmcp_origins(["https://tools.example.com?unsafe=true"])


def test_registry_revision_is_stable_and_schema_sensitive() -> None:
    tools = [{"name": "read_notes", "inputSchema": {"type": "object"}}]
    first = webmcp_registry_revision("https://alexmerced.app/notes", tools)
    assert first == webmcp_registry_revision("https://alexmerced.app/notes", tools)
    assert first != webmcp_registry_revision(
        "https://alexmerced.app/notes", [{"name": "write_notes"}]
    )


@pytest.mark.asyncio
async def test_webmcp_invocation_validates_arguments_before_page_code(monkeypatch) -> None:
    class FakePage:
        url = "https://alexmerced.app/tools"

        async def evaluate(self, script, _arguments=None):
            if "values?." in script:
                return [
                    {
                        "name": "lookup",
                        "inputSchema": {
                            "type": "object",
                            "required": ["query"],
                            "properties": {"query": {"type": "string"}},
                        },
                        "annotations": {"readOnlyHint": True},
                    }
                ]
            raise AssertionError("invalid arguments must not reach page code")

    class FakeContext:
        async def close(self):
            return None

    class FakePlaywright:
        async def stop(self):
            return None

    async def fake_page(*_args, **_kwargs):
        return FakePlaywright(), FakeContext(), FakePage()

    monkeypatch.setattr("magent.browser._webmcp_page", fake_page)
    result = await webmcp_invoke("https://alexmerced.app/tools", "lookup", {})

    assert result["ok"] is False
    assert result["error_code"] == "WEBMCP_ARGUMENT_VALIDATION_FAILED"
