"""CLI-first configuration helpers for MagAgent."""

from __future__ import annotations

import os
from typing import Any

from magent.config import (
    load_global_config,
    load_user_profile,
    save_global_config,
    save_user_profile,
)
from magent.setup import DEFAULT_MODELS, PROVIDER_CHOICES

MODEL_ROLES = ("coding", "review", "memory", "cheap", "fallback")
GATEWAY_PLATFORMS = ("slack", "discord", "telegram")


def provider_choices() -> list[dict[str, str]]:
    """Return known provider choices for friendly CLI display."""
    return [
        {"id": provider_id, "label": label, "default_model": DEFAULT_MODELS.get(provider_id, "")}
        for provider_id, label in PROVIDER_CHOICES
    ]


def detect_provider_environment() -> list[dict[str, Any]]:
    """Detect likely provider readiness from env vars and local defaults."""
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "nous-portal": "NOUS_API_KEY",
        "opencode-zen": "OPENCODE_ZEN_KEY",
        "google": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    detected = []
    for item in provider_choices():
        provider_id = item["id"]
        env_var = env_map.get(provider_id, "")
        detected.append(
            {
                **item,
                "api_key_env": env_var,
                "env_present": bool(env_var and os.environ.get(env_var)),
                "local": provider_id in {"ollama", "lmstudio", "custom", "opencode-go"},
            }
        )
    return detected


def set_default_provider(
    provider_id: str,
    model: str | None = None,
    *,
    api_key_env: str = "",
    api_key: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    """Set default provider/model and provider entry in global config."""
    cfg = load_global_config()
    model = model or DEFAULT_MODELS.get(provider_id, "")
    cfg.setdefault("defaults", {})["provider"] = provider_id
    cfg.setdefault("defaults", {})["model"] = model
    entry = cfg.setdefault("providers", {}).setdefault(provider_id, {})
    if model:
        entry["default_model"] = model
    if api_key_env:
        entry["api_key_env"] = api_key_env
    if api_key:
        entry["api_key"] = api_key
    if base_url:
        entry["base_url"] = base_url
    save_global_config(cfg)
    return {"ok": True, "provider": provider_id, "model": model, "config": entry}


def set_model_role(role: str, value: str) -> dict[str, Any]:
    """Set a model role such as coding, review, memory, cheap, or fallback."""
    role = role.strip().lower()
    if role not in MODEL_ROLES:
        return {"ok": False, "error": f"Unknown model role: {role}", "known": list(MODEL_ROLES)}
    cfg = load_global_config()
    models = cfg.setdefault("models", {})
    if role == "fallback":
        models[role] = [item.strip() for item in value.split(",") if item.strip()]
    else:
        models[role] = value.strip()
    save_global_config(cfg)
    return {"ok": True, "role": role, "value": models[role]}


def clear_model_role(role: str) -> dict[str, Any]:
    """Clear a configured model role."""
    role = role.strip().lower()
    if role not in MODEL_ROLES:
        return {"ok": False, "error": f"Unknown model role: {role}", "known": list(MODEL_ROLES)}
    cfg = load_global_config()
    cfg.setdefault("models", {})[role] = [] if role == "fallback" else ""
    save_global_config(cfg)
    return {"ok": True, "role": role, "value": cfg["models"][role]}


def model_role_summary() -> dict[str, Any]:
    cfg = load_global_config()
    return {"ok": True, "roles": {role: cfg.get("models", {}).get(role, [] if role == "fallback" else "") for role in MODEL_ROLES}}


def configure_memory(
    username: str,
    *,
    mode: str = "",
    semantic: bool | None = None,
    write_every: int | None = None,
    extraction_provider: str = "",
    extraction_model: str = "",
) -> dict[str, Any]:
    """Configure memory defaults without hand-editing TOML."""
    profile = load_user_profile(username)
    memory = profile.setdefault("memory", {})
    if mode:
        normalized = mode.strip().lower()
        if normalized not in {"auto", "inbox-first", "manual"}:
            return {"ok": False, "error": "mode must be auto, inbox-first, or manual"}
        memory["auto_write"] = normalized == "auto"
        memory["inbox_first"] = normalized == "inbox-first"
    if semantic is not None:
        memory["semantic_enabled"] = semantic
    if write_every is not None:
        memory["write_every_n_turns"] = max(1, int(write_every))
    if extraction_provider:
        memory["extraction_provider"] = extraction_provider
    if extraction_model:
        memory["extraction_model"] = extraction_model
    save_user_profile(username, profile)
    return {"ok": True, "user": username, "memory": memory}


def configure_subagents(
    *,
    max_subagents: int | None = None,
    max_parallel: int | None = None,
    model_role: str = "",
    sandbox_mode: str = "",
) -> dict[str, Any]:
    """Configure subagent caps and defaults."""
    cfg = load_global_config()
    subagents = cfg.setdefault("subagents", {})
    if max_subagents is not None:
        subagents["max_subagents"] = max(0, int(max_subagents))
    if max_parallel is not None:
        subagents["max_parallel_subagents"] = max(1, int(max_parallel))
    if model_role:
        subagents["model_role"] = model_role
    if sandbox_mode:
        subagents["sandbox_mode"] = sandbox_mode
    save_global_config(cfg)
    return {"ok": True, "subagents": subagents}


def configure_gateway(
    platform: str,
    *,
    bot_token: str = "",
    app_token: str = "",
    allowed_user_ids: list[str] | None = None,
    allowed_channel_ids: list[str] | None = None,
    rate_limit: int | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Configure gateway platform tokens and shared gateway limits."""
    platform = platform.strip().lower()
    if platform not in GATEWAY_PLATFORMS:
        return {"ok": False, "error": f"Unknown gateway platform: {platform}", "known": list(GATEWAY_PLATFORMS)}
    cfg = load_global_config()
    gateway = cfg.setdefault("gateway", {})
    if allowed_user_ids is not None:
        gateway["allowed_user_ids"] = allowed_user_ids
    if allowed_channel_ids is not None:
        gateway["allowed_channel_ids"] = allowed_channel_ids
    if rate_limit is not None:
        gateway["rate_limit_per_minute"] = max(1, int(rate_limit))
    if timeout_seconds is not None:
        gateway["max_task_duration_seconds"] = max(30, int(timeout_seconds))
    platform_cfg = gateway.setdefault(platform, {})
    if bot_token:
        platform_cfg["bot_token"] = bot_token
    if app_token:
        platform_cfg["app_token"] = app_token
    platform_cfg.setdefault("bot_token", "")
    if platform == "slack":
        platform_cfg.setdefault("app_token", "")
    save_global_config(cfg)
    return {"ok": True, "platform": platform, "gateway": _redact_gateway(gateway)}


def ux_doctor(username: str | None = None) -> dict[str, Any]:
    """Return a user-friendly readiness summary for key UX surfaces."""
    cfg = load_global_config()
    user_profile = load_user_profile(username) if username else {}
    provider = cfg.get("defaults", {}).get("provider", "")
    model = cfg.get("defaults", {}).get("model", "")
    gateway = cfg.get("gateway", {})
    subagents = cfg.get("subagents", {})
    roles = cfg.get("models", {})
    return {
        "ok": bool(provider and model),
        "provider": {"configured": bool(provider), "provider": provider, "model": model},
        "model_roles": {role: bool(roles.get(role)) for role in MODEL_ROLES},
        "memory": {
            "auto_write": user_profile.get("memory", {}).get("auto_write", cfg.get("memory", {}).get("auto_write", True)),
            "inbox_first": user_profile.get("memory", {}).get("inbox_first", False),
            "semantic_enabled": user_profile.get("memory", {}).get("semantic_enabled", cfg.get("memory", {}).get("semantic_enabled", True)),
        },
        "gateways": {
            platform: bool(gateway.get(platform, {}).get("bot_token")) for platform in GATEWAY_PLATFORMS
        },
        "subagents": {
            "max_subagents": subagents.get("max_subagents", cfg.get("agent", {}).get("max_subagents", 3)),
            "max_parallel_subagents": subagents.get("max_parallel_subagents", 2),
            "model_role": subagents.get("model_role", "coding"),
            "sandbox_mode": subagents.get("sandbox_mode", ""),
        },
    }


def _redact_gateway(gateway: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in gateway.items():
        if isinstance(value, dict):
            redacted[key] = {k: ("***" if "token" in k and v else v) for k, v in value.items()}
        else:
            redacted[key] = value
    return redacted
