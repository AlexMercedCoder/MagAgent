"""Prompt-cache helpers for provider calls and diagnostics."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from magent.tokens import estimate_tokens


@dataclass(frozen=True)
class CacheCapabilities:
    provider: str
    implicit_prefix_cache: bool = False
    explicit_cache_control: bool = False
    prompt_cache_key: bool = False
    prompt_cache_retention: bool = False
    session_id: bool = False
    explicit_cached_content: bool = False
    usage_fields: tuple[str, ...] = ()
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


CACHE_CAPABILITIES: dict[str, CacheCapabilities] = {
    "openai": CacheCapabilities(
        provider="openai",
        implicit_prefix_cache=True,
        prompt_cache_key=True,
        prompt_cache_retention=True,
        usage_fields=("prompt_tokens_details.cached_tokens",),
        notes="Automatic exact-prefix caching starts on sufficiently large repeated prefixes.",
    ),
    "anthropic": CacheCapabilities(
        provider="anthropic",
        explicit_cache_control=True,
        usage_fields=("cache_read_input_tokens", "cache_creation_input_tokens"),
        notes="Best results come from explicit cache checkpoints around stable system/tool text.",
    ),
    "google": CacheCapabilities(
        provider="google",
        implicit_prefix_cache=True,
        explicit_cached_content=True,
        usage_fields=("usage_metadata.cached_content_token_count",),
        notes="Gemini supports implicit caching and explicit cached content for large contexts.",
    ),
    "deepseek": CacheCapabilities(
        provider="deepseek",
        implicit_prefix_cache=True,
        usage_fields=("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"),
        notes="DeepSeek exposes prompt-cache hit and miss token counters.",
    ),
    "openrouter": CacheCapabilities(
        provider="openrouter",
        implicit_prefix_cache=True,
        session_id=True,
        notes="Caching depends on the routed upstream provider; session_id helps sticky routing.",
    ),
    "bedrock": CacheCapabilities(
        provider="bedrock",
        explicit_cache_control=True,
        usage_fields=("cacheReadInputTokens", "cacheWriteInputTokens"),
        notes="Bedrock model support varies; use cache checkpoints where supported.",
    ),
    "opencode-go": CacheCapabilities(
        provider="opencode-go",
        implicit_prefix_cache=True,
        notes="OpenAI-compatible endpoint; cache behavior depends on the upstream model gateway.",
    ),
    "opencode-zen": CacheCapabilities(
        provider="opencode-zen",
        implicit_prefix_cache=True,
        notes="OpenAI-compatible endpoint; cache behavior depends on the upstream model gateway.",
    ),
    "nous": CacheCapabilities(
        provider="nous",
        implicit_prefix_cache=True,
        notes="OpenAI-compatible endpoint; cache behavior depends on the selected model.",
    ),
    "custom": CacheCapabilities(
        provider="custom",
        notes="Custom OpenAI-compatible endpoint; inspect provider docs for cache support.",
    ),
}


def provider_cache_capabilities(provider_id: str) -> CacheCapabilities:
    """Return known prompt-cache capabilities for a provider."""
    return CACHE_CAPABILITIES.get(
        provider_id,
        CacheCapabilities(provider=provider_id, notes="No provider-specific cache behavior known."),
    )


def cache_key_for(
    provider_id: str,
    model: str,
    username: str,
    project_slug: str | None,
    session_id: str | None,
    cwd: str,
    *,
    scope: str = "project",
) -> str:
    """Build a stable provider cache key without exposing local paths."""
    parts = [provider_id, model]
    if scope == "session":
        parts.extend([username, project_slug or "", session_id or ""])
    elif scope == "user":
        parts.append(username)
    else:
        project_fingerprint = project_slug or Path(cwd).resolve(strict=False).name or "project"
        parts.extend([username, project_fingerprint])
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"magent-{scope}-{digest}"


def build_cache_request_kwargs(
    provider_id: str,
    model: str,
    config: Any,
    *,
    username: str = "",
    project_slug: str | None = None,
    session_id: str | None = None,
    cwd: str = ".",
) -> dict[str, Any]:
    """Build provider-safe request kwargs that improve cache affinity."""
    if not getattr(config, "prompt_caching", True):
        return {}

    caps = provider_cache_capabilities(provider_id)
    scope = getattr(config, "prompt_cache_key_scope", "project")
    cache_key = cache_key_for(
        provider_id,
        model,
        username or "default",
        project_slug,
        session_id,
        cwd,
        scope=scope,
    )
    kwargs: dict[str, Any] = {}
    if caps.prompt_cache_key:
        kwargs["prompt_cache_key"] = cache_key
        retention = getattr(config, "prompt_cache_retention", "")
        if retention:
            kwargs["prompt_cache_retention"] = retention
    if caps.session_id:
        kwargs["session_id"] = cache_key
    return kwargs


def extract_cache_usage(usage: Any) -> dict[str, int | str]:
    """Normalize cache usage fields from common provider response shapes."""
    cached_tokens = _int_path(usage, "prompt_tokens_details", "cached_tokens")
    cache_write_tokens = 0
    cache_miss_tokens = 0
    cache_source = ""

    deepseek_hit = _int_path(usage, "prompt_cache_hit_tokens")
    deepseek_miss = _int_path(usage, "prompt_cache_miss_tokens")
    if deepseek_hit or deepseek_miss:
        cached_tokens = cached_tokens or deepseek_hit
        cache_miss_tokens = deepseek_miss
        cache_source = "deepseek"

    anthropic_read = _int_path(usage, "cache_read_input_tokens")
    anthropic_write = _int_path(usage, "cache_creation_input_tokens")
    if anthropic_read or anthropic_write:
        cached_tokens = cached_tokens or anthropic_read
        cache_write_tokens = anthropic_write
        cache_source = "anthropic"

    google_cached = _int_path(usage, "usage_metadata", "cached_content_token_count")
    if google_cached:
        cached_tokens = cached_tokens or google_cached
        cache_source = "google"

    bedrock_read = _int_path(usage, "cacheReadInputTokens")
    bedrock_write = _int_path(usage, "cacheWriteInputTokens")
    if bedrock_read or bedrock_write:
        cached_tokens = cached_tokens or bedrock_read
        cache_write_tokens = cache_write_tokens or bedrock_write
        cache_source = "bedrock"

    if cached_tokens and not cache_source:
        cache_source = "prompt_tokens_details"

    return {
        "cached_tokens": cached_tokens,
        "cache_hit_tokens": cached_tokens,
        "cache_miss_tokens": cache_miss_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_source": cache_source,
    }


def cache_doctor_data(
    provider_id: str,
    model: str,
    stable_prefix: str,
    volatile_context: str,
    config: Any,
) -> dict[str, Any]:
    """Return prompt-cache readiness diagnostics."""
    caps = provider_cache_capabilities(provider_id)
    stable_tokens = estimate_tokens(stable_prefix)
    volatile_tokens = estimate_tokens(volatile_context)
    min_stable = int(getattr(config, "prompt_cache_min_stable_tokens", 1024))
    recommendations: list[str] = []
    if not getattr(config, "prompt_caching", True):
        recommendations.append("Prompt caching is disabled in context.prompt_caching.")
    if stable_tokens < min_stable and caps.implicit_prefix_cache:
        recommendations.append(
            f"Stable prefix is about {stable_tokens} tokens; many providers cache after {min_stable}+ repeated prefix tokens."
        )
    if caps.explicit_cache_control:
        recommendations.append(
            "Provider supports explicit cache checkpoints; enable after live smoke testing provider compatibility."
        )
    if not (
        caps.implicit_prefix_cache
        or caps.explicit_cache_control
        or caps.prompt_cache_key
        or caps.session_id
        or caps.explicit_cached_content
    ):
        recommendations.append("No known provider cache controls; MagAgent will still keep prompts cache-friendly.")
    return {
        "provider": provider_id,
        "model": model,
        "enabled": bool(getattr(config, "prompt_caching", True)),
        "capabilities": caps.as_dict(),
        "stable_prefix_tokens": stable_tokens,
        "volatile_context_tokens": volatile_tokens,
        "min_stable_prefix_tokens": min_stable,
        "request_hints": build_cache_request_kwargs(
            provider_id,
            model,
            config,
            username="diagnostic",
            project_slug="project",
            session_id="session",
            cwd=".",
        ),
        "recommendations": recommendations,
    }


def _int_path(obj: Any, *path: str) -> int:
    cur = obj
    for key in path:
        if cur is None:
            return 0
        cur = cur.get(key) if isinstance(cur, dict) else getattr(cur, key, None)
    try:
        return int(cur or 0)
    except (TypeError, ValueError):
        return 0
