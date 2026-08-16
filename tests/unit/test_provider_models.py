from __future__ import annotations

from types import SimpleNamespace

import magent.provider_models as provider_models
from magent.provider_models import discover_provider_models, recommend_provider_model


class Store:
    def __init__(self):
        self.data = {}

    def read(self, name, default):
        return self.data.get(name, default)

    def write(self, name, data):
        self.data[name] = data


class Config:
    default_model = "fallback"

    def provider_config(self, provider_id):
        return {"base_url": "https://example.test/v1"}

    def resolve_api_key(self, provider_id):
        return "key"


def test_discover_provider_models_fetches_and_caches(monkeypatch) -> None:
    store = Store()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "deepseek/deepseek-v4-flash"}, {"id": "nousresearch/hermes-4-70b"}]}

    monkeypatch.setattr(provider_models.httpx, "get", lambda *args, **kwargs: Response())

    result = discover_provider_models(Config(), store, "nous-portal", refresh=True)
    cached = discover_provider_models(Config(), store, "nous-portal")

    assert result["source"] == "live"
    assert result["count"] == 2
    assert cached["cached"] is True


def test_discovery_normalizes_alias_and_rejects_unknown_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_models,
        "_fetch_provider_models",
        lambda *_args, **_kwargs: ["deepseek/deepseek-v4-flash"],
    )
    config = Config()
    store = Store()

    alias = discover_provider_models(config, store, "nous", refresh=True)
    unknown_config = SimpleNamespace(
        provider_config=lambda _provider: {},
        resolve_api_key=lambda _provider: None,
    )
    unknown = discover_provider_models(unknown_config, store, "nouse", refresh=True)

    assert alias["provider"] == "nous-portal"
    assert alias["ok"] is True
    assert unknown == {
        "ok": False,
        "provider": "nouse",
        "models": [],
        "error": "Unknown provider",
    }


def test_recommend_provider_model_prefers_health_then_hints() -> None:
    store = Store()
    store.write(
        "model_health",
        [
            {
                "provider": "nous-portal",
                "model": "deepseek/deepseek-v4-flash",
                "task_type": "tool-use",
                "ok": True,
                "created_at": "2026-01-01T00:00:00Z",
            }
        ],
    )

    result = recommend_provider_model(SimpleNamespace(provider_config=lambda _: {}, resolve_api_key=lambda _: None), store, "nous-portal")

    assert result["ok"] is True
    assert result["source"] == "health"
    assert result["recommendation"]["model"] == "deepseek/deepseek-v4-flash"


def test_parse_native_model_responses() -> None:
    assert provider_models._parse_model_response(
        {"data": [{"id": "gpt-5"}, {"id": "gpt-5-mini"}]},
        response_format="openai",
    ) == ["gpt-5", "gpt-5-mini"]
    assert provider_models._parse_model_response(
        {"models": [{"model": "qwen3:8b"}, {"name": "gemma3"}]},
        response_format="ollama",
    ) == ["gemma3", "qwen3:8b"]
    assert provider_models._parse_model_response(
        {
            "models": [
                {
                    "name": "models/gemini-3.6-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/gemini-embedding-001",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        },
        response_format="gemini",
    ) == ["gemini-3.6-flash"]


def test_refresh_failure_uses_stale_cache(monkeypatch) -> None:
    store = Store()
    provider_models.save_provider_models(
        store,
        "nous-portal",
        ["deepseek/deepseek-v4-flash", "nousresearch/hermes-4-70b"],
        source="live",
    )
    monkeypatch.setattr(
        provider_models,
        "_fetch_provider_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = discover_provider_models(Config(), store, "nous-portal", refresh=True)

    assert result["ok"] is True
    assert result["source"] == "cache-stale"
    assert result["cached"] is True
    assert "offline" in result["warning"]


def test_ranked_choices_prioritize_default_and_chat_models() -> None:
    ranked = provider_models.ranked_model_choices(
        ["text-embedding-3-small", "claude-sonnet-5", "gpt-5-mini"],
        default_model="gpt-5-mini",
    )

    assert ranked[0] == "gpt-5-mini"
    assert ranked[-1] == "text-embedding-3-small"


def test_fetch_native_provider_models_uses_expected_auth(monkeypatch) -> None:
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "claude-sonnet-5"}]}

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(provider_models.httpx, "get", fake_get)

    models = provider_models._fetch_provider_models(
        "anthropic",
        {},
        base_url=None,
        api_key="secret",
        timeout=7,
    )

    assert models == ["claude-sonnet-5"]
    assert calls[0][0].startswith("https://api.anthropic.com/v1/models")
    assert calls[0][1]["headers"] == {
        "x-api-key": "secret",
        "anthropic-version": "2023-06-01",
    }
    assert calls[0][1]["timeout"] == 7


def test_fetch_ollama_models_does_not_require_credentials(monkeypatch) -> None:
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"model": "qwen3:8b"}]}

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(provider_models.httpx, "get", fake_get)

    models = provider_models._fetch_provider_models(
        "ollama",
        {},
        base_url="http://ollama.test:11434",
        api_key=None,
        timeout=3,
    )

    assert models == ["qwen3:8b"]
    assert calls == [("http://ollama.test:11434/api/tags", {"timeout": 3})]
