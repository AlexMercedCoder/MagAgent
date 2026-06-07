"""Provider metadata shared by setup, config UX, and runtime adapters."""

from __future__ import annotations

from typing import Any

PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "opencode-go": {
        "label": "OpenCode Go subscription (low-cost open coding models)",
        "display": "OpenCode Go",
        "default_model": "deepseek-v4-flash",
        "env": "OPENCODE_GO_KEY",
        "access_mode": "subscription",
        "base_url": "https://opencode.ai/zen/go/v1",
        "litellm": "openai-compatible",
    },
    "ollama": {
        "label": "Ollama (local — FREE, requires Ollama running)",
        "display": "Ollama (local)",
        "default_model": "qwen2.5-coder:32b",
        "access_mode": "local",
        "base_url": "http://localhost:11434",
        "litellm": "ollama",
        "local": True,
    },
    "lmstudio": {
        "label": "LM Studio (local OpenAI-compatible server)",
        "display": "LM Studio (local)",
        "default_model": "local-model",
        "access_mode": "local",
        "base_url": "http://localhost:1234/v1",
        "litellm": "openai-compatible",
        "local": True,
    },
    "openai": {
        "label": "OpenAI API (GPT-4o, GPT-5; use Codex mode for ChatGPT plan access)",
        "display": "OpenAI",
        "default_model": "gpt-5",
        "env": "OPENAI_API_KEY",
        "access_mode": "api",
        "litellm": "openai",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "display": "Anthropic",
        "default_model": "claude-sonnet-4-5",
        "env": "ANTHROPIC_API_KEY",
        "access_mode": "api",
        "litellm": "anthropic",
    },
    "nous-portal": {
        "label": "Nous Portal (Hermes 4 + 200+ models)",
        "display": "Nous Portal",
        "default_model": "deepseek/deepseek-v4-flash",
        "env": "NOUS_API_KEY",
        "access_mode": "api",
        "base_url": "https://inference-api.nousresearch.com/v1",
        "litellm": "openai-compatible",
    },
    "opencode-zen": {
        "label": "OpenCode Zen pay-as-you-go (premium curated models)",
        "display": "OpenCode Zen",
        "default_model": "deepseek-v4-flash",
        "env": "OPENCODE_ZEN_KEY",
        "access_mode": "payg",
        "base_url": "https://opencode.ai/zen/v1",
        "litellm": "openai-compatible",
    },
    "google": {
        "label": "Google Gemini",
        "display": "Google Gemini",
        "default_model": "gemini-2.0-flash",
        "env": "GEMINI_API_KEY",
        "access_mode": "api",
        "litellm": "gemini",
    },
    "groq": {
        "label": "Groq (fast inference)",
        "display": "Groq",
        "default_model": "llama-3.3-70b-versatile",
        "env": "GROQ_API_KEY",
        "access_mode": "api",
        "litellm": "groq",
    },
    "openrouter": {
        "label": "OpenRouter (aggregator)",
        "display": "OpenRouter",
        "default_model": "deepseek/deepseek-chat",
        "env": "OPENROUTER_API_KEY",
        "access_mode": "api",
        "litellm": "openrouter",
    },
    "bedrock": {
        "label": "AWS Bedrock (uses AWS credentials/profile)",
        "display": "AWS Bedrock",
        "default_model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "access_mode": "aws",
        "litellm": "bedrock",
    },
    "mistral": {
        "label": "Mistral AI",
        "display": "Mistral AI",
        "default_model": "mistral-large-latest",
        "env": "MISTRAL_API_KEY",
        "access_mode": "api",
        "litellm": "mistral",
    },
    "deepseek": {
        "label": "DeepSeek API",
        "display": "DeepSeek",
        "default_model": "deepseek-chat",
        "env": "DEEPSEEK_API_KEY",
        "access_mode": "api",
        "litellm": "deepseek",
    },
    "xai": {
        "label": "xAI Grok",
        "display": "xAI",
        "default_model": "grok-4",
        "env": "XAI_API_KEY",
        "access_mode": "api",
        "litellm": "xai",
    },
    "perplexity": {
        "label": "Perplexity Sonar",
        "display": "Perplexity",
        "default_model": "sonar-pro",
        "env": "PERPLEXITYAI_API_KEY",
        "access_mode": "api",
        "litellm": "perplexity",
    },
    "cerebras": {
        "label": "Cerebras Inference",
        "display": "Cerebras",
        "default_model": "llama3.1-8b",
        "env": "CEREBRAS_API_KEY",
        "access_mode": "api",
        "litellm": "cerebras",
    },
    "together_ai": {
        "label": "Together AI",
        "display": "Together AI",
        "default_model": "moonshotai/Kimi-K2.5",
        "env": "TOGETHERAI_API_KEY",
        "access_mode": "api",
        "litellm": "together_ai",
    },
    "fireworks_ai": {
        "label": "Fireworks AI",
        "display": "Fireworks AI",
        "default_model": "accounts/fireworks/models/deepseek-coder-v2-instruct",
        "env": "FIREWORKS_API_KEY",
        "access_mode": "api",
        "litellm": "fireworks_ai",
    },
    "deepinfra": {
        "label": "DeepInfra",
        "display": "DeepInfra",
        "default_model": "openai/gpt-oss-120b",
        "env": "DEEPINFRA_API_KEY",
        "access_mode": "api",
        "litellm": "deepinfra",
    },
    "custom": {
        "label": "Custom OpenAI-compatible endpoint",
        "display": "Custom Endpoint",
        "default_model": "your-model-name",
        "access_mode": "api",
        "litellm": "openai-compatible",
    },
}

PROVIDER_ORDER = [
    "opencode-go",
    "ollama",
    "lmstudio",
    "openai",
    "anthropic",
    "nous-portal",
    "opencode-zen",
    "google",
    "groq",
    "openrouter",
    "bedrock",
    "mistral",
    "deepseek",
    "xai",
    "perplexity",
    "cerebras",
    "together_ai",
    "fireworks_ai",
    "deepinfra",
    "custom",
]

OPENAI_COMPATIBLE_PROVIDERS = {
    provider_id
    for provider_id, metadata in PROVIDER_CATALOG.items()
    if metadata.get("litellm") == "openai-compatible"
}


def provider_metadata(provider_id: str) -> dict[str, Any]:
    return PROVIDER_CATALOG.get(provider_id, {})


def provider_choices() -> list[tuple[str, str]]:
    return [(provider_id, PROVIDER_CATALOG[provider_id]["label"]) for provider_id in PROVIDER_ORDER]


def default_models() -> dict[str, str]:
    return {provider_id: PROVIDER_CATALOG[provider_id]["default_model"] for provider_id in PROVIDER_ORDER}


def provider_display_names() -> dict[str, str]:
    return {provider_id: PROVIDER_CATALOG[provider_id]["display"] for provider_id in PROVIDER_ORDER}


def provider_base_urls() -> dict[str, str]:
    return {
        provider_id: metadata["base_url"]
        for provider_id, metadata in PROVIDER_CATALOG.items()
        if metadata.get("base_url")
    }


def provider_env_vars() -> dict[str, str]:
    return {
        provider_id: metadata["env"]
        for provider_id, metadata in PROVIDER_CATALOG.items()
        if metadata.get("env")
    }


def default_access_modes() -> dict[str, str]:
    return {
        provider_id: metadata["access_mode"]
        for provider_id, metadata in PROVIDER_CATALOG.items()
        if metadata.get("access_mode")
    }


def validate_provider_catalog() -> dict[str, Any]:
    """Validate provider catalog metadata for setup/runtime/doc consistency."""
    required = ("label", "display", "default_model", "access_mode", "litellm")
    issues: list[dict[str, str]] = []
    for provider_id in PROVIDER_ORDER:
        metadata = PROVIDER_CATALOG.get(provider_id)
        if not metadata:
            issues.append({"provider": provider_id, "field": "catalog", "error": "missing provider metadata"})
            continue
        for field in required:
            if not metadata.get(field):
                issues.append({"provider": provider_id, "field": field, "error": "required field is empty"})
        if (
            not metadata.get("local")
            and metadata.get("access_mode") == "api"
            and provider_id != "custom"
            and not metadata.get("env")
            and metadata.get("litellm") != "bedrock"
        ):
            issues.append({"provider": provider_id, "field": "env", "error": "API provider should declare an env var"})
    extra = sorted(set(PROVIDER_CATALOG) - set(PROVIDER_ORDER))
    for provider_id in extra:
        issues.append({"provider": provider_id, "field": "order", "error": "provider missing from PROVIDER_ORDER"})
    return {"ok": not issues, "providers": len(PROVIDER_ORDER), "issues": issues}
