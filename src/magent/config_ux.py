"""CLI-first configuration helpers for MagAgent."""

from __future__ import annotations

import os
import shutil
from typing import Any

from magent import config as magent_config
from magent.config import (
    load_global_config,
    load_user_profile,
    save_global_config,
    save_user_profile,
)
from magent.provider_catalog import (
    PROVIDER_CATALOG,
    PROVIDER_ORDER,
    default_access_modes,
    default_models,
    provider_env_vars,
    provider_metadata,
    validate_provider_catalog,
)
from magent.provider_catalog import (
    provider_choices as catalog_provider_choices,
)

MODEL_ROLES = ("coding", "review", "memory", "cheap", "image_maker", "fallback")
GATEWAY_PLATFORMS = ("slack", "discord", "telegram")
DEFAULT_MODELS = default_models()
PROVIDER_CHOICES = catalog_provider_choices()
IMAGE_MODEL_CHOICES = (
    {
        "id": "openai-gpt-image",
        "label": "OpenAI GPT Image",
        "provider": "openai",
        "model": "gpt-image-1",
        "value": "openai/gpt-image-1",
        "api_key_env": "OPENAI_API_KEY",
        "access_mode": "api",
    },
    {
        "id": "custom",
        "label": "Custom provider/model",
        "provider": "",
        "model": "",
        "value": "",
        "api_key_env": "",
        "access_mode": "api",
    },
)
PROVIDER_ACCESS_MODES: dict[str, list[dict[str, str]]] = {
    "openai": [
        {
            "id": "api",
            "label": "OpenAI API key",
            "description": "Use MagAgent's in-process LiteLLM provider with OPENAI_API_KEY.",
        },
        {
            "id": "codex",
            "label": "Codex via ChatGPT plan",
            "description": "Use Codex CLI subscription/login for delegated coding workflows.",
        },
    ],
    "opencode-zen": [
        {
            "id": "payg",
            "label": "OpenCode Zen pay-as-you-go",
            "description": "Use Zen credits/API key for curated models.",
        }
    ],
    "opencode-go": [
        {
            "id": "subscription",
            "label": "OpenCode Go subscription",
            "description": "Use the Go subscription API key and Go model endpoint.",
        }
    ],
    "bedrock": [
        {
            "id": "aws",
            "label": "AWS credentials",
            "description": "Use AWS profile/environment credentials for Bedrock.",
        }
    ],
}


def _tighten_global_config_permissions() -> None:
    try:
        if magent_config.GLOBAL_CONFIG.exists():
            magent_config.GLOBAL_CONFIG.chmod(0o600)
    except OSError:
        pass


DEFAULT_ACCESS_MODE = default_access_modes()


def provider_choices() -> list[dict[str, str]]:
    """Return known provider choices for friendly CLI display."""
    return [
        {
            "id": provider_id,
            "label": label,
            "default_model": DEFAULT_MODELS.get(provider_id, ""),
            "recommended_access": DEFAULT_ACCESS_MODE.get(provider_id, "api"),
        }
        for provider_id, label in PROVIDER_CHOICES
    ]


def provider_access_modes(provider_id: str) -> list[dict[str, str]]:
    """Return access mode choices for a provider."""
    return PROVIDER_ACCESS_MODES.get(
        provider_id,
        [
            {
                "id": "api",
                "label": "API key or local endpoint",
                "description": "Use the provider through MagAgent's in-process LiteLLM adapter.",
            }
        ],
    )


def detect_provider_environment() -> list[dict[str, Any]]:
    """Detect likely provider readiness from env vars and local defaults."""
    env_map = provider_env_vars()
    detected = []
    for item in provider_choices():
        provider_id = item["id"]
        env_var = env_map.get(provider_id, "")
        access_modes = provider_access_modes(provider_id)
        detected.append(
            {
                **item,
                "api_key_env": env_var,
                "env_present": bool(env_var and os.environ.get(env_var)),
                "access_modes": access_modes,
                "codex_cli": shutil.which("codex") if provider_id == "openai" else "",
                "local": bool(provider_metadata(provider_id).get("local")) or provider_id == "custom",
            }
        )
    return detected


def provider_matrix() -> dict[str, Any]:
    """Return catalog-backed provider capability/readiness rows."""
    cfg = load_global_config()
    providers = cfg.get("providers", {})
    detected = {item["id"]: item for item in detect_provider_environment()}
    rows = []
    for provider_id in PROVIDER_ORDER:
        metadata = PROVIDER_CATALOG[provider_id]
        provider_cfg = providers.get(provider_id, {})
        env_var = metadata.get("env", "")
        readiness = provider_readiness(provider_id, provider_cfg)
        rows.append(
            {
                "id": provider_id,
                "display": metadata["display"],
                "default_model": metadata["default_model"],
                "access_mode": provider_cfg.get("access_mode") or metadata["access_mode"],
                "env": env_var,
                "env_present": readiness["env_present"],
                "credential_configured": readiness["credential_configured"],
                "ready": readiness["ready"],
                "reason": readiness["reason"],
                "local": bool(metadata.get("local")) or provider_id == "custom",
                "litellm": metadata["litellm"],
                "configured": provider_id in providers,
                "detected": detected.get(provider_id, {}),
            }
        )
    return {"ok": True, "providers": rows}


def provider_explain(provider_id: str) -> dict[str, Any]:
    """Explain one provider and how to configure it."""
    metadata = provider_metadata(provider_id)
    if not metadata:
        return {"ok": False, "error": f"Unknown provider: {provider_id}", "known": PROVIDER_ORDER}
    cfg = load_global_config()
    provider_cfg = cfg.get("providers", {}).get(provider_id, {})
    readiness = provider_readiness(provider_id, provider_cfg)
    env_var = provider_cfg.get("api_key_env") or metadata.get("env", "")
    return {
        "ok": True,
        "provider": provider_id,
        "metadata": metadata,
        "configured": provider_id in cfg.get("providers", {}),
        "access_modes": provider_access_modes(provider_id),
        "env_present": readiness["env_present"],
        "credential_configured": readiness["credential_configured"],
        "ready": readiness["ready"],
        "reason": readiness["reason"],
        "commands": [
            f"magent provider set {provider_id} --model {metadata['default_model']}"
            + (f" --api-key-env {env_var}" if env_var else ""),
            f"magent provider test {provider_id}",
        ],
    }


def provider_env_status() -> dict[str, Any]:
    """Return provider env var readiness plus actionable export hints."""
    rows = []
    for provider_id in PROVIDER_ORDER:
        metadata = PROVIDER_CATALOG[provider_id]
        env_var = metadata.get("env", "")
        rows.append(
            {
                "provider": provider_id,
                "env": env_var,
                "present": bool(env_var and os.environ.get(env_var)),
                "required": bool(env_var),
                "fix": f"export {env_var}=..." if env_var and not os.environ.get(env_var) else "",
            }
        )
    return {"ok": True, "providers": rows}


def provider_recommend(goal: str = "coding") -> dict[str, Any]:
    """Recommend provider candidates for a usage goal."""
    goal = goal.strip().lower() or "coding"
    tiers = {
        "local": ["ollama", "lmstudio"],
        "cheap": ["opencode-go", "deepseek", "groq", "deepinfra"],
        "coding": ["openai", "anthropic", "opencode-go", "deepseek", "mistral"],
        "review": ["anthropic", "openai", "mistral", "xai"],
        "memory": ["ollama", "openai", "mistral", "deepseek"],
        "research": ["perplexity", "openai", "xai", "openrouter"],
    }
    matrix = {item["id"]: item for item in provider_matrix()["providers"]}
    return {
        "ok": True,
        "goal": goal,
        "recommendations": [
            {**matrix[provider_id], "reason": _recommendation_reason(goal, provider_id)}
            for provider_id in tiers.get(goal, tiers["coding"])
            if provider_id in matrix
        ],
    }


def provider_catalog_doctor() -> dict[str, Any]:
    """Validate provider metadata and docs-adjacent catalog health."""
    return validate_provider_catalog()


def set_default_provider(
    provider_id: str,
    model: str | None = None,
    *,
    api_key_env: str = "",
    api_key: str = "",
    api_key_keyring: str = "",
    base_url: str = "",
    access_mode: str = "",
) -> dict[str, Any]:
    """Set default provider/model and provider entry in global config."""
    cfg = load_global_config()
    model = model or DEFAULT_MODELS.get(provider_id, "")
    access_mode = access_mode or DEFAULT_ACCESS_MODE.get(provider_id, "api")
    cfg.setdefault("defaults", {})["provider"] = provider_id
    cfg.setdefault("defaults", {})["model"] = model
    entry = cfg.setdefault("providers", {}).setdefault(provider_id, {})
    if model:
        entry["default_model"] = model
    entry["access_mode"] = access_mode
    if api_key_env:
        entry["api_key_env"] = api_key_env
    if api_key:
        entry["api_key"] = api_key
    if api_key_keyring:
        entry["api_key_keyring"] = api_key_keyring
    if base_url:
        entry["base_url"] = base_url
    save_global_config(cfg)
    if api_key:
        _tighten_global_config_permissions()
    return {
        "ok": True,
        "provider": provider_id,
        "model": model,
        "access_mode": access_mode,
        "config": _redact_provider_entry(entry),
    }


def configure_provider_entry(
    provider_id: str,
    *,
    model: str = "",
    api_key_env: str = "",
    api_key: str = "",
    api_key_keyring: str = "",
    base_url: str = "",
    access_mode: str = "",
) -> dict[str, Any]:
    """Configure provider credentials without changing the default chat provider."""
    provider_id = provider_id.strip()
    if not provider_id:
        return {"ok": False, "error": "provider_id is required"}
    cfg = load_global_config()
    entry = cfg.setdefault("providers", {}).setdefault(provider_id, {})
    if model:
        entry["default_model"] = model
    if access_mode:
        entry["access_mode"] = access_mode
    elif provider_id in PROVIDER_CATALOG:
        entry.setdefault("access_mode", DEFAULT_ACCESS_MODE.get(provider_id, "api"))
    if api_key_env:
        entry["api_key_env"] = api_key_env
    if api_key:
        entry["api_key"] = api_key
    if api_key_keyring:
        entry["api_key_keyring"] = api_key_keyring
    if base_url:
        entry["base_url"] = base_url
    save_global_config(cfg)
    if api_key:
        _tighten_global_config_permissions()
    return {"ok": True, "provider": provider_id, "config": _redact_provider_entry(entry)}


def image_model_choices() -> list[dict[str, str]]:
    """Return recommended image-maker model presets for setup wizards."""
    return [dict(item) for item in IMAGE_MODEL_CHOICES]


def set_model_role(role: str, value: str) -> dict[str, Any]:
    """Set a model role such as coding, review, memory, cheap, image_maker, or fallback."""
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


def model_role_health() -> dict[str, Any]:
    """Return readiness diagnostics for configured model roles."""
    cfg = load_global_config()
    providers = cfg.get("providers", {})
    rows = []
    for role in MODEL_ROLES:
        value = cfg.get("models", {}).get(role, [] if role == "fallback" else "")
        values = value if isinstance(value, list) else ([value] if value else [])
        checks = [_model_value_health(item, providers) for item in values if item]
        rows.append(
            {
                "role": role,
                "configured": bool(values),
                "value": value,
                "checks": checks,
                "ok": bool(values) and all(item["ok"] for item in checks),
            }
        )
    return {"ok": all(row["ok"] or not row["configured"] for row in rows), "roles": rows}


def orchestration_role_doctor(
    *,
    planning_role: str = "review",
    execution_role: str = "coding",
) -> dict[str, Any]:
    """Return readiness for model roles used by staged goal orchestration."""
    cfg = magent_config.load_config(magent_config.get_current_user())
    rows = []
    env_vars = provider_env_vars()
    for role, purpose in [(planning_role, "planning"), (execution_role, "execution")]:
        provider_id, model = cfg.provider_and_model_for_role(role)
        provider_cfg = cfg.provider_config(provider_id)
        configured = bool(model)
        rows.append(
            {
                "purpose": purpose,
                "role": role,
                "provider": provider_id,
                "model": model,
                "configured": configured,
                "provider_known": bool(provider_cfg) or provider_id in PROVIDER_CATALOG,
                "api_key_env": provider_cfg.get("api_key_env") or env_vars.get(provider_id, ""),
                "ready_hint": (
                    "ready if provider credentials are valid"
                    if configured
                    else f"set with `magent model set-role {role} provider/model`"
                ),
            }
        )
    return {"ok": all(item["configured"] and item["provider_known"] for item in rows), "roles": rows}


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


def _model_value_health(value: str, providers: dict[str, Any]) -> dict[str, Any]:
    provider_id = value.split("/", 1)[0] if "/" in value else ""
    model = value.split("/", 1)[1] if "/" in value else value
    if not provider_id:
        return {
            "ok": False,
            "value": value,
            "provider": "",
            "model": model,
            "reason": "Use provider/model format for explicit role routing.",
        }
    metadata = PROVIDER_CATALOG.get(provider_id)
    if not metadata:
        return {
            "ok": False,
            "value": value,
            "provider": provider_id,
            "model": model,
            "reason": "Unknown provider.",
        }
    provider_cfg = providers.get(provider_id, {})
    readiness = provider_readiness(provider_id, provider_cfg)
    env_var = provider_cfg.get("api_key_env") or metadata.get("env", "")
    access_mode = provider_cfg.get("access_mode") or metadata.get("access_mode", "api")
    return {
        "ok": readiness["ready"],
        "value": value,
        "provider": provider_id,
        "model": model,
        "env": env_var,
        "access_mode": access_mode,
        "reason": readiness["reason"],
    }


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
        "provider": {
            "configured": bool(provider),
            "provider": provider,
            "model": model,
            "access_mode": cfg.get("providers", {}).get(provider, {}).get(
                "access_mode", DEFAULT_ACCESS_MODE.get(provider, "api")
            ),
        },
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


def doctor_actions(username: str | None = None) -> dict[str, Any]:
    """Return actionable readiness checks with suggested commands."""
    summary = ux_doctor(username)
    cfg = load_global_config()
    provider = summary["provider"]["provider"]
    provider_cfg = cfg.get("providers", {}).get(provider, {})
    access_mode = summary["provider"].get("access_mode", "api")
    actions: list[dict[str, Any]] = []

    def add(key: str, ok: bool, detail: str, command: str = "", fixable: bool = False) -> None:
        actions.append(
            {
                "key": key,
                "ok": ok,
                "detail": detail,
                "command": command,
                "fixable": fixable,
            }
        )

    add("provider", bool(provider), f"{provider or 'not configured'} / {summary['provider']['model']}", "magent provider wizard")
    if provider == "openai" and access_mode == "codex":
        add(
            "codex_cli",
            shutil.which("codex") is not None,
            "Codex CLI is required for ChatGPT plan access.",
            "codex login",
        )
    elif provider_cfg.get("api_key_env"):
        env = provider_cfg["api_key_env"]
        add(f"{provider}_api_key", bool(os.environ.get(env)), f"Environment variable {env}", f"export {env}=...")
    elif provider_cfg.get("api_key"):
        add(f"{provider}_api_key", True, "Inline API key is configured.")
    if provider == "opencode-go":
        readiness = provider_readiness(provider, provider_cfg)
        add(
            "opencode_go",
            access_mode == "subscription" and readiness["credential_configured"],
            "OpenCode Go subscription credentials are configured.",
            "magent provider set opencode-go --access subscription",
            True,
        )
    if not any(summary["model_roles"].values()):
        add("model_roles", False, "No model roles are configured.", "magent model wizard", True)
    else:
        add("model_roles", True, "At least one model role is configured.", "magent model roles")
    add(
        "memory",
        bool(summary["memory"].get("semantic_enabled") or summary["memory"].get("inbox_first")),
        "Memory is configured for semantic recall or inbox review.",
        "magent memory wizard",
        True,
    )
    add(
        "subagents",
        int(summary["subagents"].get("max_subagents", 0)) > 0,
        f"max={summary['subagents'].get('max_subagents')} parallel={summary['subagents'].get('max_parallel_subagents')}",
        "magent subagent configure --max 3 --parallel 2",
        True,
    )
    return {"ok": all(item["ok"] for item in actions), "summary": summary, "actions": actions}


def fix_doctor_actions(username: str | None = None) -> dict[str, Any]:
    """Apply safe local fixes for doctor findings."""
    before = doctor_actions(username)
    cfg = load_global_config()
    if not any(cfg.get("models", {}).get(role) for role in MODEL_ROLES):
        default_model = cfg.get("defaults", {}).get("model", "")
        if default_model:
            cfg.setdefault("models", {})["coding"] = default_model
            cfg.setdefault("models", {})["review"] = default_model
    cfg.setdefault("subagents", {}).setdefault("max_subagents", 3)
    cfg.setdefault("subagents", {}).setdefault("max_parallel_subagents", 2)
    provider = cfg.get("defaults", {}).get("provider", "")
    if provider:
        cfg.setdefault("providers", {}).setdefault(provider, {})["access_mode"] = DEFAULT_ACCESS_MODE.get(provider, "api")
    save_global_config(cfg)
    after = doctor_actions(username)
    return {"ok": after["ok"], "before": before, "after": after}


def _redact_gateway(gateway: dict[str, Any]) -> dict[str, Any]:
    redacted = {}
    for key, value in gateway.items():
        if isinstance(value, dict):
            redacted[key] = {k: ("***" if "token" in k and v else v) for k, v in value.items()}
        else:
            redacted[key] = value
    return redacted


def _redact_provider_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: ("***" if "key" in key.lower() and value else value) for key, value in entry.items()}


def provider_readiness(provider_id: str, provider_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return non-secret provider readiness details."""
    provider_cfg = provider_cfg or {}
    metadata = PROVIDER_CATALOG.get(provider_id, {})
    access_mode = provider_cfg.get("access_mode") or metadata.get("access_mode", "api")
    env_var = provider_cfg.get("api_key_env") or metadata.get("env", "")
    env_present = bool(env_var and os.environ.get(env_var))
    inline_key = bool(provider_cfg.get("api_key"))
    local = bool(metadata.get("local")) or access_mode == "local" or provider_id in {"custom", "ollama", "lmstudio"}
    aws = access_mode == "aws"
    codex = provider_id == "openai" and access_mode == "codex"
    codex_ready = shutil.which("codex") is not None if codex else False
    credential_configured = env_present or inline_key
    ready = local or aws or codex_ready or credential_configured
    if local:
        reason = "local provider"
    elif aws:
        reason = "AWS credential chain"
    elif codex:
        reason = "Codex CLI available" if codex_ready else "Codex CLI not found"
    elif inline_key:
        reason = "inline API key configured"
    elif env_present:
        reason = f"environment variable {env_var} is present"
    elif env_var:
        reason = f"environment variable {env_var} is missing"
    else:
        reason = "no credential required" if ready else "not configured"
    return {
        "ready": ready,
        "credential_configured": credential_configured,
        "env": env_var,
        "env_present": env_present,
        "access_mode": access_mode,
        "reason": reason,
    }


def _recommendation_reason(goal: str, provider_id: str) -> str:
    reasons = {
        ("local", "ollama"): "Local, private, and no API key required.",
        ("local", "lmstudio"): "Local OpenAI-compatible server with GUI-managed models.",
        ("cheap", "opencode-go"): "Subscription-oriented low-cost coding models.",
        ("cheap", "deepseek"): "Strong low-cost coding/chat API.",
        ("cheap", "groq"): "Fast inference for open-weight models.",
        ("coding", "openai"): "Strong default for broad coding tasks.",
        ("coding", "anthropic"): "Strong code editing and review model family.",
        ("review", "anthropic"): "Good fit for careful review and reasoning.",
        ("research", "perplexity"): "Search/research-oriented Sonar models.",
        ("memory", "ollama"): "Cheap local extraction and embedding workflows.",
    }
    return reasons.get((goal, provider_id), PROVIDER_CATALOG.get(provider_id, {}).get("label", provider_id))
