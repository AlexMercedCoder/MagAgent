"""Provider model discovery, caching, and recommendations."""

from __future__ import annotations

from typing import Any

import httpx

from magent.model_health import recommend_model_from_health
from magent.provider_catalog import PROVIDER_CATALOG
from magent.workbench_store import now_iso

MODEL_CATALOG_STORE = "provider_model_catalogs"

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
) -> dict[str, Any]:
    """Discover provider models, using a cache unless refresh is requested."""
    if not refresh:
        cached = cached_provider_models(store, provider_id)
        if cached:
            return {**cached, "cached": True}

    metadata = PROVIDER_CATALOG.get(provider_id, {})
    configured = config.provider_config(provider_id)
    base_url = configured.get("base_url") or metadata.get("base_url")
    api_key = config.resolve_api_key(provider_id)
    if metadata.get("litellm") == "openai-compatible" and base_url and api_key:
        try:
            models = _fetch_openai_compatible_models(base_url, api_key, timeout=timeout)
            return {**save_provider_models(store, provider_id, models, source="live"), "cached": False}
        except Exception as e:
            fallback = _catalog_fallback(provider_id, metadata, str(e))
            return fallback
    return _catalog_fallback(provider_id, metadata, "live discovery unavailable")


def recommend_provider_model(
    config: Any,
    store: Any,
    provider_id: str,
    *,
    goal: str = "tool-use",
) -> dict[str, Any]:
    """Recommend a model using health observations first, then catalog/discovery hints."""
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


def _fetch_openai_compatible_models(base_url: str, api_key: str, *, timeout: int) -> list[str]:
    url = base_url.rstrip("/") + "/models"
    response = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return [str(item.get("id", "")) for item in data.get("data", []) if item.get("id")]


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
