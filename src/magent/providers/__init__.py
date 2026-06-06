"""LLM provider abstraction layer for MagAgent.

Uses LiteLLM for unified access to all providers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from rich.console import Console

console = Console()

# Provider base URL registry
PROVIDER_BASE_URLS: dict[str, str] = {
    "nous-portal": "https://inference-api.nousresearch.com/v1",
    "opencode-zen": "https://opencode.ai/zen/v1",
    "opencode-go": "https://opencode.ai/zen/go/v1",
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234/v1",
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "nous-portal": "Nous Portal",
    "opencode-zen": "OpenCode Zen",
    "opencode-go": "OpenCode Go",
    "ollama": "Ollama (local)",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "bedrock": "AWS Bedrock",
    "lmstudio": "LM Studio (local)",
    "custom": "Custom Endpoint",
}


def _build_litellm_model(provider: str, model: str) -> str:
    """Build the LiteLLM model string for a given provider/model pair."""
    if provider == "ollama":
        return f"ollama/{model}"
    if provider == "openai":
        return model  # LiteLLM handles openai natively
    if provider == "anthropic":
        return model if model.startswith("claude") else f"anthropic/{model}"
    if provider == "google":
        return f"gemini/{model}" if not model.startswith("gemini/") else model
    if provider == "groq":
        return f"groq/{model}"
    if provider == "openrouter":
        return f"openrouter/{model}"
    if provider == "bedrock":
        return f"bedrock/{model}"
    # For custom OpenAI-compat providers (nous-portal, opencode-zen, lmstudio, custom)
    return f"openai/{model}"


def _build_api_kwargs(
    provider: str,
    model: str,
    provider_cfg: dict[str, Any],
    api_key: str | None,
) -> dict[str, Any]:
    """Build kwargs dict for litellm.acompletion."""
    litellm_model = _build_litellm_model(provider, model)

    kwargs: dict[str, Any] = {"model": litellm_model}

    # Custom base URL — always set for non-native providers
    base_url = provider_cfg.get("base_url") or PROVIDER_BASE_URLS.get(provider)
    if base_url and provider not in (
        "openai",
        "anthropic",
        "google",
        "groq",
        "openrouter",
        "bedrock",
    ):
        kwargs["api_base"] = base_url

    # Resolve API key: passed-in > direct config > dummy for local endpoints
    resolved_key = api_key or provider_cfg.get("api_key")
    if resolved_key:
        kwargs["api_key"] = resolved_key
    elif provider in ("nous-portal", "opencode-zen", "opencode-go", "lmstudio", "custom", "ollama"):
        kwargs["api_key"] = "sk-magent"  # dummy for local/custom OpenAI-compat endpoints

    return kwargs


class Provider:
    """Wraps LiteLLM for a specific provider/model."""

    def __init__(
        self,
        provider_id: str,
        model: str,
        api_key: str | None = None,
        provider_cfg: dict[str, Any] | None = None,
    ):
        self.provider_id = provider_id
        self.model = model
        self.api_key = api_key
        self.provider_cfg = provider_cfg or {}
        self._base_kwargs = _build_api_kwargs(provider_id, model, self.provider_cfg, api_key)

    @property
    def display_name(self) -> str:
        name = PROVIDER_DISPLAY_NAMES.get(self.provider_id, self.provider_id)
        return f"{name} / {self.model}"

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Non-streaming completion. Returns full response string."""
        try:
            import litellm

            litellm.suppress_debug_info = True

            response = await litellm.acompletion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **self._base_kwargs,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise ProviderError(f"Provider '{self.provider_id}' error: {e}") from e

    async def stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Streaming completion. Yields token chunks."""
        try:
            import litellm

            litellm.suppress_debug_info = True

            response = await litellm.acompletion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **self._base_kwargs,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            raise ProviderError(f"Streaming error from '{self.provider_id}': {e}") from e

    def as_extract_fn(self):
        """Return an async callable for memory extraction (non-streaming)."""

        async def _fn(messages: list[dict[str, str]]) -> str:
            return await self.complete(messages, temperature=0.1, max_tokens=2048)

        return _fn


class ProviderError(Exception):
    pass


def build_provider(
    provider_id: str,
    model: str,
    api_key: str | None,
    provider_cfg: dict[str, Any] | None = None,
) -> Provider:
    """Factory: build a Provider instance."""
    return Provider(
        provider_id=provider_id,
        model=model,
        api_key=api_key,
        provider_cfg=provider_cfg or {},
    )


async def test_provider(provider: Provider) -> bool:
    """Send a minimal ping to verify the provider works."""
    try:
        response = await provider.complete(
            [{"role": "user", "content": "Say 'OK' and nothing else."}],
            max_tokens=10,
        )
        return bool(response.strip())
    except Exception:
        return False
