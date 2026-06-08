from __future__ import annotations

from types import SimpleNamespace

from magent.cache import (
    build_cache_request_kwargs,
    cache_doctor_data,
    cache_key_for,
    extract_cache_usage,
    provider_cache_capabilities,
)


class FakeConfig:
    prompt_caching = True
    prompt_cache_key_scope = "project"
    prompt_cache_retention = ""
    prompt_cache_min_stable_tokens = 1024


def test_provider_cache_capabilities_cover_major_providers() -> None:
    assert provider_cache_capabilities("openai").prompt_cache_key is True
    assert provider_cache_capabilities("anthropic").explicit_cache_control is True
    assert provider_cache_capabilities("deepseek").implicit_prefix_cache is True


def test_cache_key_is_stable_and_redacted() -> None:
    first = cache_key_for("openai", "gpt-5", "alex", "repo", "s1", "/private/path")
    second = cache_key_for("openai", "gpt-5", "alex", "repo", "s2", "/private/path")
    assert first == second
    assert first.startswith("magent-project-")
    assert "private" not in first


def test_build_cache_request_kwargs_uses_provider_safe_hints() -> None:
    openai = build_cache_request_kwargs(
        "openai",
        "gpt-5",
        FakeConfig(),
        username="alex",
        project_slug="repo",
        session_id="s1",
    )
    openrouter = build_cache_request_kwargs(
        "openrouter",
        "deepseek/deepseek-chat",
        FakeConfig(),
        username="alex",
        project_slug="repo",
    )
    assert sorted(openai) == ["prompt_cache_key"]
    assert sorted(openrouter) == ["session_id"]


def test_extract_cache_usage_normalizes_common_shapes() -> None:
    openai = SimpleNamespace(
        prompt_tokens_details=SimpleNamespace(cached_tokens=256),
    )
    deepseek = {"prompt_cache_hit_tokens": 128, "prompt_cache_miss_tokens": 64}
    anthropic = {"cache_read_input_tokens": 300, "cache_creation_input_tokens": 80}

    assert extract_cache_usage(openai)["cached_tokens"] == 256
    assert extract_cache_usage(deepseek)["cache_miss_tokens"] == 64
    assert extract_cache_usage(anthropic)["cache_write_tokens"] == 80


def test_cache_doctor_data_reports_request_hints() -> None:
    data = cache_doctor_data("openai", "gpt-5", "stable text", "", FakeConfig())
    assert data["provider"] == "openai"
    assert "prompt_cache_key" in data["request_hints"]
    assert data["stable_prefix_tokens"] >= 1
