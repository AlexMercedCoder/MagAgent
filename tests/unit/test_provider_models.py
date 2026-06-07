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
