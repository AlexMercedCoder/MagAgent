from __future__ import annotations

from types import SimpleNamespace

from magent.daily_driver import build_goal_prompt
from magent.session_controls import last_user_message, pop_last_turn
from magent.tool_gateway import explain_backend, gateway_status
from magent.tools.executor import ToolExecutor


def test_goal_prompt_contains_dependency_and_artifact_recovery_guidance() -> None:
    prompt = build_goal_prompt("create astrojs markdown blog where the build succeeds")

    assert "Continue until the measurable goal is complete" in prompt
    assert "Astro/AstroJS projects install the npm package `astro`, not `astrojs`" in prompt
    assert "Every requested file exists and has non-placeholder content" in prompt
    assert "immediately retry with complete content" in prompt


def test_read_only_fetch_pipeline_trust_pattern_is_broad_but_scoped() -> None:
    executor = ToolExecutor(cwd=".", interactive_permissions=False)

    pattern = executor._shell_trust_pattern("curl -s https://example.com | grep title | head -5", 2)

    assert pattern == "curl * | *"
    assert executor._shell_trust_pattern("curl -X POST https://example.com | head", 2) != "curl * | *"


def test_session_retry_and_undo_helpers() -> None:
    conversation = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "done again"},
    ]

    assert last_user_message(conversation) == "second"
    removed = pop_last_turn(conversation)

    assert removed["user"] == "second"
    assert removed["assistant"] == "done again"
    assert last_user_message(conversation) == "first"


def test_tool_gateway_reports_configured_backends() -> None:
    config = SimpleNamespace(
        get=lambda *keys, default=None: {"nous-portal": {}, "opencode-go": {}}
        if keys == ("providers",)
        else {"github": {}}
        if keys == ("mcp", "servers")
        else default,
        model_for_role=lambda role: "openai/gpt-image-1" if role == "image_maker" else "",
    )

    status = gateway_status(config)

    enabled = {item["id"] for item in status["backends"] if item["enabled"]}
    assert {"local", "web", "image", "nous-portal", "opencode-go", "mcp"} <= enabled
    assert explain_backend("nous-portal")["subscription"] is True
