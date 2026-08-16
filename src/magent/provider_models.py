"""Provider model discovery, caching, and recommendations."""

from __future__ import annotations

from typing import Any

import httpx

from magent.model_health import recommend_model_from_health
from magent.provider_catalog import PROVIDER_CATALOG, canonical_provider_id
from magent.workbench_store import now_iso

MODEL_CATALOG_STORE = "provider_model_catalogs"

# Providers with native or well-known OpenAI-compatible model-list APIs. The
# catalog remains the fallback because subscription backends and private
# gateways do not always expose model discovery to every account.
MODEL_DISCOVERY_ENDPOINTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1/models", "openai"),
    "anthropic": ("https://api.anthropic.com/v1/models?limit=1000", "anthropic"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", "gemini"),
    "groq": ("https://api.groq.com/openai/v1/models", "openai"),
    "openrouter": ("https://openrouter.ai/api/v1/models", "openai"),
    "mistral": ("https://api.mistral.ai/v1/models", "openai"),
    "deepseek": ("https://api.deepseek.com/models", "openai"),
    "xai": ("https://api.x.ai/v1/models", "openai"),
    "cerebras": ("https://api.cerebras.ai/v1/models", "openai"),
    "together_ai": ("https://api.together.xyz/v1/models", "openai"),
    "fireworks_ai": ("https://api.fireworks.ai/inference/v1/models", "openai"),
    "deepinfra": ("https://api.deepinfra.com/v1/openai/models", "openai"),
}

GOAL_HINTS: dict[str, list[str]] = {
    "cheap": ["flash", "mini", "lite", "small", "8b", "deepseek-v4-flash"],
    "tool-use": ["deepseek-v4-flash", "claude", "gpt", "hermes", "coder"],
    "coding": ["coder", "deepseek", "claude", "gpt", "qwen", "kimi"],
    "review": ["claude", "gpt", "reason", "pro", "sonnet"],
    "planning": ["claude", "gpt", "reason", "pro", "sonnet"],
}


def cached_provider_models(store: Any, provider_id: str) -> dict[str, Any] | None:
    catalogs = store.read(MODEL_CATALOG_STORE, {})
    item = catalogs.get(provider_id)
    return item if isinstance(item, dict) else None


def save_provider_models(store: Any, provider_id: str, models: list[str], *, source: str) -> dict[str, Any]:
    catalogs = store.read(MODEL_CATALOG_STORE, {})
    item = {
        "ok": True,
        "provider": provider_id,
        "models": sorted(set(models)),
        "count": len(set(models)),
        "source": source,
        "refreshed_at": now_iso(),
    }
    catalogs[provider_id] = item
    store.write(MODEL_CATALOG_STORE, catalogs)
    return item


def discover_provider_models(
    config: Any,
    store: Any,
    provider_id: str,
    *,
    refresh: bool = False,
    timeout: int = 20,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Discover provider models, using a cache unless refresh is requested."""
    provider_id = canonical_provider_id(provider_id)
    if provider_id not in PROVIDER_CATALOG and not config.provider_config(provider_id).get(
        "base_url"
    ):
        return {"ok": False, "provider": provider_id, "models": [], "error": "Unknown provider"}
    if not refresh:
        cached = cached_provider_models(store, provider_id)
        if cached:
            return {**cached, "cached": True}

    metadata = PROVIDER_CATALOG.get(provider_id, {})
    configured = config.provider_config(provider_id)
    resolved_base_url = base_url or configured.get("base_url") or metadata.get("base_url")
    resolved_api_key = api_key or config.resolve_api_key(provider_id)
    try:
        models = _fetch_provider_models(
            provider_id,
            metadata,
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            timeout=timeout,
        )
        if models:
            return {
                **save_provider_models(store, provider_id, models, source="live"),
                "cached": False,
            }
    except Exception as error:
        cached = cached_provider_models(store, provider_id)
        if cached:
            return {
                **cached,
                "source": "cache-stale",
                "cached": True,
                "warning": f"Live refresh failed: {error}",
            }
        return _catalog_fallback(provider_id, metadata, str(error))
    return _catalog_fallback(provider_id, metadata, "live discovery unavailable")


def recommend_provider_model(
    config: Any,
    store: Any,
    provider_id: str,
    *,
    goal: str = "tool-use",
) -> dict[str, Any]:
    """Recommend a model using health observations first, then catalog/discovery hints."""
    provider_id = canonical_provider_id(provider_id)
    health = recommend_model_from_health(store, provider=provider_id, task_type=goal)
    if health.get("ok"):
        return {"ok": True, "source": "health", **health}
    catalog = discover_provider_models(config, store, provider_id)
    models = catalog.get("models", [])
    hints = GOAL_HINTS.get(goal, GOAL_HINTS["tool-use"])
    scored = sorted(models, key=lambda model: _score_model(model, hints), reverse=True)
    if not scored:
        return {"ok": False, "error": "No models found.", "provider": provider_id}
    return {
        "ok": True,
        "source": catalog.get("source", "catalog"),
        "provider": provider_id,
        "goal": goal,
        "model": scored[0],
        "candidates": scored[:10],
    }


def _fetch_provider_models(
    provider_id: str,
    metadata: dict[str, Any],
    *,
    base_url: str | None,
    api_key: str | None,
    timeout: int,
) -> list[str]:
    if provider_id == "ollama":
        url = (base_url or "http://localhost:11434").rstrip("/") + "/api/tags"
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        return _parse_model_response(response.json(), response_format="ollama")

    endpoint = MODEL_DISCOVERY_ENDPOINTS.get(provider_id)
    if endpoint:
        if not api_key:
            raise ValueError("provider credential is not available for model discovery")
        url, response_format = endpoint
        headers = _model_headers(response_format, api_key)
        response = httpx.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return _parse_model_response(response.json(), response_format=response_format)

    if metadata.get("litellm") == "openai-compatible" and base_url:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = httpx.get(
            base_url.rstrip("/") + "/models",
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return _parse_model_response(response.json(), response_format="openai")
    return []


def _model_headers(response_format: str, api_key: str) -> dict[str, str]:
    if response_format == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if response_format == "gemini":
        return {"x-goog-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _parse_model_response(payload: Any, *, response_format: str) -> list[str]:
    if isinstance(payload, list):
        items = payload
    elif response_format in {"ollama", "gemini"}:
        items = payload.get("models", []) if isinstance(payload, dict) else []
    else:
        items = payload.get("data", []) if isinstance(payload, dict) else []

    models: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if response_format == "gemini":
            actions = item.get("supportedGenerationMethods") or item.get("supported_actions") or []
            if actions and "generateContent" not in actions:
                continue
            model = item.get("baseModelId") or item.get("name") or item.get("id")
        elif response_format == "ollama":
            model = item.get("model") or item.get("name")
        else:
            model = item.get("id") or item.get("name")
        value = str(model or "").strip()
        if value.startswith("models/"):
            value = value.removeprefix("models/")
        if value:
            models.append(value)
    return sorted(set(models))


def ranked_model_choices(models: list[str], *, default_model: str = "") -> list[str]:
    """Rank likely chat/coding models ahead of utility and dated variants."""
    hints = GOAL_HINTS["tool-use"] + GOAL_HINTS["coding"]

    def rank(model: str) -> tuple[int, int, int, str]:
        lower = model.lower()
        utility = any(
            token in lower
            for token in (
                "embedding",
                "moderation",
                "rerank",
                "whisper",
                "transcri",
                "tts",
                "image",
                "audio",
                "realtime",
            )
        )
        return (
            1 if model == default_model else 0,
            0 if utility else 1,
            sum(1 for hint in hints if hint.lower() in lower),
            lower,
        )

    return sorted(set(models), key=rank, reverse=True)


def filter_model_choices(models: list[str], query: str) -> list[str]:
    """Case-insensitive model picker filtering."""
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return list(models)
    return [model for model in models if all(term in model.lower() for term in terms)]


def _fetch_openai_compatible_models(base_url: str, api_key: str, *, timeout: int) -> list[str]:
    """Compatibility wrapper retained for callers and older integrations."""
    response = httpx.get(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return _parse_model_response(response.json(), response_format="openai")


def _catalog_fallback(provider_id: str, metadata: dict[str, Any], reason: str) -> dict[str, Any]:
    model = metadata.get("default_model", "")
    return {
        "ok": bool(model),
        "provider": provider_id,
        "models": [model] if model else [],
        "count": 1 if model else 0,
        "source": "catalog",
        "cached": False,
        "refreshed_at": "",
        "warning": reason,
    }


def _score_model(model: str, hints: list[str]) -> tuple[int, int]:
    lower = model.lower()
    score = sum(1 for hint in hints if hint.lower() in lower)
    return score, -len(model)
