"""First-run readiness for the local Web UI.

`magent doctor` reads the machine and says what is missing. The browser assumed
all of it was already done: open `magent ui` on a machine with no provider and
the first message failed with a credential error, having never said that no
provider was chosen.

This exposes the same readiness signal the CLI reports and lets a provider,
model, and optional credential be configured from the loopback, token-gated UI.
Credentials default to the OS keyring; explicit config-file storage is supported
with a visible warning for systems where keyring integration is unavailable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Providers that run without any credential, so a first run is always possible.
LOCAL_PROVIDERS = ("ollama", "lmstudio")

# The probe below runs on every boot, so it has to fail fast rather than make
# the browser wait on a runtime that is not there.
LOCAL_PROBE_TIMEOUT_SECONDS = 1.5

# Where each local runtime answers when it is up.
_LOCAL_PROBE_PATHS = {"ollama": "/api/tags", "lmstudio": "/v1/models"}


def _local_reachable(provider: str, base_url: str) -> tuple[bool, str]:
    """Is the local runtime actually answering?

    The shipped default provider is `ollama`, and a local provider needs no
    credential, so readiness reported "ready" on a machine where Ollama had
    never been installed. The composer then failed on the first message with a
    connection error. Naming a local runtime is not the same as running one.
    """
    import httpx

    from magent.provider_catalog import PROVIDER_CATALOG

    root = (base_url or str(PROVIDER_CATALOG.get(provider, {}).get("base_url") or "")).rstrip("/")
    if not root:
        return True, "no endpoint to probe"
    url = root + _LOCAL_PROBE_PATHS.get(provider, "/v1/models")
    try:
        response = httpx.get(url, timeout=LOCAL_PROBE_TIMEOUT_SECONDS)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - any failure means "not usable yet"
        return False, f"{web_label(provider)} is not answering at {root}"
    return True, f"{web_label(provider)} is running at {root}"


def _default_provider() -> tuple[str, str]:
    """The provider and model the user actually chose, or ("", "").

    `load_global_config()` merges in the shipped defaults (Ollama with
    qwen2.5-coder:32b), so on a machine nobody had configured the setup panel
    said "ollama is configured, but ollama is not answering" and preselected
    it. Only a choice written to config.toml counts as configured.
    """
    import tomllib

    from magent import config as magent_config

    path = Path(magent_config.GLOBAL_CONFIG)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return "", ""
    defaults = raw.get("defaults", {}) if isinstance(raw.get("defaults"), dict) else {}
    return str(defaults.get("provider") or ""), str(defaults.get("model") or "")


# Short names, groups and one-line hints for the setup panel. The catalog
# labels are written for the terminal wizard ("Ollama (local — FREE, requires
# Ollama running)", "OpenAI API (GPT-4o, GPT-5; ...)"): too long for a select,
# inconsistent, and some name models that go stale.
_WEB_NAMES = {
    "opencode-go": "OpenCode Go",
    "ollama": "Ollama",
    "lmstudio": "LM Studio",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "nous-portal": "Nous Portal",
    "opencode-zen": "OpenCode Zen",
    "google": "Google Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "trusted-router": "TrustedRouter",
    "prime-intellect": "Prime Intellect",
    "bedrock": "AWS Bedrock",
    "mistral": "Mistral AI",
    "deepseek": "DeepSeek",
    "xai": "xAI",
    "perplexity": "Perplexity",
    "cerebras": "Cerebras",
    "together_ai": "Together AI",
    "fireworks_ai": "Fireworks AI",
    "deepinfra": "DeepInfra",
    "custom": "Custom OpenAI-compatible endpoint",
    "mock": "Mock (offline demo)",
}
_WEB_HINTS = {
    "ollama": "Runs open models on this computer. Needs Ollama running; no API key.",
    "lmstudio": "Runs models on this computer through LM Studio's local server; no API key.",
    "openai": "Needs an OpenAI API key. For a ChatGPT plan, use Codex mode from the terminal.",
    "opencode-go": "OpenCode Go subscription with low-cost open coding models.",
    "opencode-zen": "OpenCode Zen pay-as-you-go account with curated models.",
    "nous-portal": "Nous Portal account, with Hermes and many other models.",
    "openrouter": "One key for many hosted models.",
    "trusted-router": "Private, attested OpenAI-compatible routing.",
    "bedrock": "Uses your AWS credentials or profile.",
    "custom": "Any OpenAI-compatible server; set its URL with `magent provider set custom`.",
    "mock": "Canned replies, no model and no key: see the whole workflow offline.",
}
_ADVANCED = {"custom", "bedrock", "mock"}


def web_label(name: str) -> str:
    """The short, consistent name the Web UI shows for a provider."""
    from magent.provider_catalog import PROVIDER_CATALOG

    if name in _WEB_NAMES:
        return _WEB_NAMES[name]
    label = str((PROVIDER_CATALOG.get(name, {}) or {}).get("label") or name)
    return label.split(" (")[0]


def readiness() -> dict[str, Any]:
    """The same question `magent doctor` answers: can this machine run a turn?"""
    from magent.config import load_global_config
    from magent.config_ux import provider_readiness

    config = load_global_config()
    provider, model = _default_provider()
    providers = config.get("providers", {}) or {}

    credential: dict[str, Any] = {"ready": False, "reason": "No provider selected yet."}
    if provider:
        credential = provider_readiness(provider, providers.get(provider, {}))

    local = provider in LOCAL_PROVIDERS
    if local:
        # `provider_readiness` calls any local provider ready because it needs
        # no key. That is true of the credential and false of the runtime.
        running, detail = _local_reachable(
            provider, str(providers.get(provider, {}).get("base_url") or "")
        )
        credential = {**credential, "ready": running, "reason": detail}
    steps: list[dict[str, Any]] = [
        {
            "id": "provider",
            "label": "Provider",
            "ok": bool(provider),
            "detail": provider or "No default provider is set.",
            "action": "Choose a provider below, or run `magent setup`.",
        },
        {
            "id": "model",
            "label": "Model",
            # A provider without an explicit model still has a catalog default,
            # so this reports the choice rather than gating on it.
            "ok": True,
            "local": local,
            "detail": model or "The provider's default model will be used.",
            "action": "Ready for model work.",
        },
        {
            "id": "credential",
            # A local runtime has no credential to report; what matters is
            # whether it is running.
            "label": "Local runtime" if local else "Credential",
            "ok": bool(credential.get("ready")),
            "detail": str(credential.get("reason") or ""),
            "env": str(credential.get("env") or ""),
            "action": (
                "Choose a provider first."
                if not provider
                else f"Start {web_label(provider)}, or choose a hosted provider below."
                if local
                else (
                    "Export the provider's key in the shell that runs `magent ui`, "
                    "or store it with `magent auth add`."
                )
            ),
        },
        {
            "id": "workspace",
            "label": "Workspace",
            "ok": True,
            "detail": os.getcwd(),
            "action": "Ready.",
        },
    ]

    # Only the provider and its credential decide whether a first message can
    # succeed; the model falls back to a catalog default and the workspace is
    # wherever the server was started.
    blocking = [
        step for step in steps if step["id"] in {"provider", "credential"} and not step["ok"]
    ]

    reason = ""
    if blocking:
        # Naming the wrong thing is worse than saying nothing: the panel used to
        # claim "no provider is configured" while the provider step showed a tick
        # and the real problem was a local runtime that was not running.
        first = blocking[0]["id"]
        detail = str(credential.get("reason") or "it cannot be used yet").rstrip(".")
        reason = (
            "No provider is configured yet, so a message sent now would fail."
            if first == "provider"
            else f"{web_label(provider)} is selected, but {detail[:1].lower() + detail[1:]}."
        )
        if first != "provider" and local and detail.startswith(web_label(provider)):
            reason = f"{detail}. Start it, or choose another provider below."

    return {
        "ok": True,
        "ready": not blocking,
        "reason": reason,
        "local": local,
        "provider": provider,
        "model": model,
        "steps": steps,
        "blocking": [step["id"] for step in blocking],
    }


def providers() -> dict[str, Any]:
    """Providers that can be selected, and where each expects its key."""
    from magent.config import load_global_config
    from magent.config_ux import DEFAULT_MODELS, image_model_choices, provider_readiness
    from magent.provider_catalog import PROVIDER_CATALOG, PROVIDER_ORDER

    config = load_global_config()
    configured = config.get("providers", {}) or {}
    default_provider, default_model = _default_provider()
    listed = []
    for name in PROVIDER_ORDER:
        metadata = PROVIDER_CATALOG.get(name, {}) or {}
        local = bool(metadata.get("local")) or name in LOCAL_PROVIDERS
        state = provider_readiness(name, configured.get(name, {}))
        listed.append(
            {
                "name": name,
                "display_name": web_label(name),
                "group": "advanced" if name in _ADVANCED else ("local" if local else "hosted"),
                "hint": _WEB_HINTS.get(name)
                or (
                    "Runs on this computer; no API key."
                    if local
                    else f"Needs an API key in {metadata.get('env')}."
                    if metadata.get("env")
                    else "Hosted provider."
                ),
                "default_model": str(DEFAULT_MODELS.get(name, "") or ""),
                "api_key_env": str(metadata.get("env", "") or ""),
                # A local runtime needs no key, so it is offered as the
                # zero-credential way to see the whole loop working.
                "needs_key": not local and bool(metadata.get("env")),
                "local": local,
                "configured": name in configured or name == default_provider,
                "credential_ready": bool(state.get("ready")),
                "credential_reason": str(state.get("reason") or ""),
            }
        )
    image_models = []
    by_name = {item["name"]: item for item in listed}
    for item in image_model_choices():
        provider = str(item.get("provider") or "")
        image_models.append(
            {
                **item,
                "available": bool(provider and by_name.get(provider, {}).get("credential_ready")),
            }
        )
    from magent.auth_store import keyring_status

    return {
        "ok": True,
        "keyring_available": bool(keyring_status()["available"]),
        "providers": listed,
        "local_providers": list(LOCAL_PROVIDERS),
        "default_provider": default_provider,
        "default_model": default_model,
        "image_models": image_models,
    }


def configure(
    provider: str,
    model: str = "",
    *,
    credential: str = "",
    credential_storage: str = "keyring",
) -> dict[str, Any]:
    """Record the provider and model choice, then re-report readiness.

    Credentials default to the OS keyring. Config-file storage is accepted only
    when the caller explicitly chooses it; config permissions are tightened by
    the shared configuration helper.
    """
    from magent.auth_store import keyring_account, keyring_status, save_keyring_secret
    from magent.config_ux import set_default_provider

    provider = (provider or "").strip()
    if not provider:
        raise ValueError("Choose a provider first.")

    secret = (credential or "").strip()
    storage = (credential_storage or "keyring").strip().lower()
    if storage not in {"keyring", "config"}:
        raise ValueError("Credential storage must be keyring or config.")
    if secret and storage == "keyring":
        status = keyring_status()
        if not status["available"]:
            raise ValueError(
                'No OS keyring is available. Choose "MagAgent config file" as the storage instead, or '
                + str(status.get("hint", ""))
            )
        stored = save_keyring_secret(provider, secret)
        if not stored.get("ok"):
            raise ValueError(str(stored.get("error") or "The key could not be stored."))
        result = set_default_provider(
            provider,
            (model or "").strip() or None,
            api_key_keyring=keyring_account(provider),
        )
    else:
        result = set_default_provider(
            provider,
            (model or "").strip() or None,
            api_key=secret if storage == "config" else "",
        )
    if not result.get("ok"):
        raise ValueError(str(result.get("error") or "That provider could not be selected."))

    state = readiness()
    state["configured"] = {"provider": result.get("provider"), "model": result.get("model")}
    state["credential_storage"] = storage if secret else "unchanged"
    return state
