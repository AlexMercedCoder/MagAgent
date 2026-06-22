from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from magent.provider_catalog import validate_provider_catalog
from magent.model_capabilities import model_capabilities
from magent.providers import (
    PROVIDER_BASE_URLS,
    PROVIDER_DISPLAY_NAMES,
    Provider,
    ProviderError,
    _build_api_kwargs,
    _build_litellm_model,
    build_provider,
)
from magent.providers import (
    test_provider as provider_health_check,
)


def test_build_litellm_model_for_supported_provider_ids() -> None:
    assert _build_litellm_model("ollama", "qwen") == "ollama/qwen"
    assert _build_litellm_model("openai", "gpt-4.1") == "gpt-4.1"
    assert _build_litellm_model("anthropic", "sonnet") == "anthropic/sonnet"
    assert _build_litellm_model("anthropic", "claude-sonnet") == "claude-sonnet"
    assert _build_litellm_model("google", "gemini-2.5") == "gemini/gemini-2.5"
    assert _build_litellm_model("google", "gemini/gemini-2.5") == "gemini/gemini-2.5"
    assert _build_litellm_model("groq", "llama") == "groq/llama"
    assert _build_litellm_model("openrouter", "deepseek/chat") == "openrouter/deepseek/chat"
    assert _build_litellm_model("bedrock", "anthropic.claude") == "bedrock/anthropic.claude"
    assert _build_litellm_model("mistral", "mistral-large-latest") == "mistral/mistral-large-latest"
    assert _build_litellm_model("deepseek", "deepseek-chat") == "deepseek/deepseek-chat"
    assert _build_litellm_model("xai", "grok-4") == "xai/grok-4"
    assert _build_litellm_model("perplexity", "sonar-pro") == "perplexity/sonar-pro"
    assert _build_litellm_model("cerebras", "llama3.1-8b") == "cerebras/llama3.1-8b"
    assert _build_litellm_model("together_ai", "moonshotai/Kimi-K2.5") == "together_ai/moonshotai/Kimi-K2.5"
    assert _build_litellm_model("fireworks_ai", "accounts/fireworks/models/deepseek-coder-v2-instruct") == (
        "fireworks_ai/accounts/fireworks/models/deepseek-coder-v2-instruct"
    )
    assert _build_litellm_model("deepinfra", "openai/gpt-oss-120b") == "deepinfra/openai/gpt-oss-120b"
    assert _build_litellm_model("custom", "model") == "openai/model"


def test_build_api_kwargs_sets_base_and_keys() -> None:
    custom = _build_api_kwargs(
        "custom",
        "model",
        {"base_url": "http://example.test/v1"},
        api_key="real-key",
    )
    local = _build_api_kwargs("ollama", "qwen", {}, api_key=None)
    native = _build_api_kwargs("openai", "gpt-4.1", {"base_url": "ignored"}, api_key="key")

    assert custom == {
        "model": "openai/model",
        "api_base": "http://example.test/v1",
        "api_key": "real-key",
    }
    assert local["api_base"] == "http://localhost:11434"
    assert local["api_key"] == "sk-magent"
    assert native == {"model": "gpt-4.1", "api_key": "key"}


def test_provider_catalog_exposes_new_easy_provider_batch() -> None:
    expected = {
        "lmstudio",
        "bedrock",
        "mistral",
        "deepseek",
        "xai",
        "perplexity",
        "cerebras",
        "together_ai",
        "fireworks_ai",
        "deepinfra",
    }

    assert expected <= set(PROVIDER_DISPLAY_NAMES)
    assert PROVIDER_BASE_URLS["lmstudio"] == "http://localhost:1234/v1"
    assert validate_provider_catalog()["ok"] is True


def test_provider_request_kwargs_adds_cache_hints() -> None:
    config = SimpleNamespace(
        prompt_caching=True,
        prompt_cache_key_scope="project",
        prompt_cache_retention="",
    )
    provider = Provider("openai", "gpt-5", api_key="key")

    kwargs = provider.request_kwargs(
        config,
        username="alex",
        project_slug="repo",
        session_id="session",
        cwd="/repo",
    )

    assert kwargs["model"] == "gpt-5"
    assert kwargs["api_key"] == "key"
    assert kwargs["prompt_cache_key"].startswith("magent-project-")


def test_model_capabilities_identify_image_models() -> None:
    caps = model_capabilities("openai", "gpt-image-1")

    assert caps["output"] == ["image"]
    assert "image" in caps["input"]
    assert caps["tools"] is False


@pytest.mark.asyncio
async def test_provider_complete_stream_and_extract_fn(monkeypatch) -> None:
    async def fake_acompletion(**kwargs):
        if kwargs.get("stream"):
            async def chunks():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="he"))]
                )
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="llo"))]
                )

            return chunks()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="complete"))]
        )

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    provider = Provider("custom", "model", provider_cfg={"base_url": "http://local"})

    assert provider.display_name == "Custom Endpoint / model"
    assert await provider.complete([{"role": "user", "content": "hi"}]) == "complete"
    assert [chunk async for chunk in provider.stream([{"role": "user", "content": "hi"}])] == [
        "he",
        "llo",
    ]
    extract = provider.as_extract_fn()
    assert await extract([{"role": "user", "content": "extract"}]) == "complete"
    assert await provider_health_check(provider) is True


@pytest.mark.asyncio
async def test_provider_wraps_litellm_errors(monkeypatch) -> None:
    async def fake_acompletion(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    provider = build_provider("openai", "gpt", api_key="key")

    with pytest.raises(ProviderError):
        await provider.complete([{"role": "user", "content": "hi"}])

    assert await provider_health_check(provider) is False


def test_provider_cooldown_records_rate_limits(tmp_path: Path, monkeypatch) -> None:
    from magent import provider_cooldown

    monkeypatch.setattr(provider_cooldown, "COOLDOWN_DIR", tmp_path)
    provider_cooldown.record_provider_cooldown("openai", 30, "429")

    remaining = provider_cooldown.provider_cooldown_remaining("openai")

    assert remaining is not None
    assert remaining > 0
    assert provider_cooldown.clear_provider_cooldown("openai")["cleared"] is True
