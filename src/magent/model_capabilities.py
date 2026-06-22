"""Lightweight model capability metadata."""

from __future__ import annotations

from typing import Any

DEFAULT_CAPABILITIES: dict[str, Any] = {
    "tools": True,
    "input": ["text"],
    "output": ["text"],
    "context_tokens": 0,
    "cost_tier": "unknown",
}

MODEL_CAPABILITY_HINTS: dict[tuple[str, str], dict[str, Any]] = {
    ("openai", "gpt-image-1"): {
        "tools": False,
        "input": ["text", "image"],
        "output": ["image"],
        "context_tokens": 0,
        "cost_tier": "image",
    },
    ("openai", "gpt-5"): {"tools": True, "input": ["text", "image"], "output": ["text"], "context_tokens": 400000},
    ("google", "gemini-2.0-flash"): {"tools": True, "input": ["text", "image"], "output": ["text"], "context_tokens": 1000000},
    ("anthropic", "claude-sonnet-4-5"): {"tools": True, "input": ["text", "image"], "output": ["text"], "context_tokens": 200000},
}


def model_capabilities(
    provider_id: str,
    model: str,
    provider_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return merged capability metadata for a provider/model."""
    caps = dict(DEFAULT_CAPABILITIES)
    lowered = model.lower()
    if any(token in lowered for token in ("image", "dall-e", "imagen")):
        caps.update({"tools": False, "input": ["text", "image"], "output": ["image"], "cost_tier": "image"})
    if any(token in lowered for token in ("gpt", "claude", "gemini", "qwen", "deepseek", "grok")):
        caps["tools"] = True
    caps.update(MODEL_CAPABILITY_HINTS.get((provider_id, model), {}))
    cfg = provider_cfg or {}
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    override = models.get(model) if isinstance(models, dict) and isinstance(models.get(model), dict) else {}
    if isinstance(override.get("capabilities"), dict):
        caps.update(override["capabilities"])
    if override.get("supports_vision") is not None:
        if bool(override["supports_vision"]) and "image" not in caps["input"]:
            caps["input"] = [*caps["input"], "image"]
        elif not bool(override["supports_vision"]):
            caps["input"] = [item for item in caps["input"] if item != "image"]
    return caps


def role_capability_summary(config: Any) -> dict[str, Any]:
    rows = {}
    for role in config.model_roles:
        provider_id, model = config.provider_and_model_for_role(role)
        rows[role] = {
            "provider": provider_id,
            "model": model,
            "capabilities": model_capabilities(provider_id, model, config.provider_config(provider_id)),
        }
    return rows
