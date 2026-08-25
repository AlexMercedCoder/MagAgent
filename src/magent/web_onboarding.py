"""First-run readiness for the local Web UI.

`magent doctor` reads the machine and says what is missing. The browser assumed
all of it was already done: open `magent ui` on a machine with no provider and
the first message failed with a credential error, having never said that no
provider was chosen.

This exposes the same readiness signal the CLI reports, and lets a provider and
model be selected from the browser. Credentials are deliberately not part of it.
`set_default_provider` accepts an inline `api_key` and writes it into the global
config file; that path is not reachable from here, so keys stay in the
environment or the system keyring and readiness reports only whether one was
found and which variable was searched.
"""

from __future__ import annotations

import os
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
        return False, f"{provider} is not answering at {root}"
    return True, f"{provider} is running at {root}"


def _default_provider() -> tuple[str, str]:
    from magent.config import load_global_config

    defaults = load_global_config().get("defaults", {}) or {}
    return str(defaults.get("provider") or ""), str(defaults.get("model") or "")


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
        running, detail = _local_reachable(provider, str(providers.get(provider, {}).get("base_url") or ""))
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
                f"Start {provider.capitalize()}, or choose a hosted provider below."
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
    blocking = [step for step in steps if step["id"] in {"provider", "credential"} and not step["ok"]]

    reason = ""
    if blocking:
        # Naming the wrong thing is worse than saying nothing: the panel used to
        # claim "no provider is configured" while the provider step showed a tick
        # and the real problem was a local runtime that was not running.
        first = blocking[0]["id"]
        reason = (
            "No provider is configured yet, so a message sent now would fail."
            if first == "provider"
            else f"{provider} is configured, but {credential.get('reason') or 'it cannot be used yet'}."
        )

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
    from magent.config_ux import DEFAULT_MODELS
    from magent.provider_catalog import PROVIDER_CATALOG, PROVIDER_ORDER

    listed = []
    for name in PROVIDER_ORDER:
        metadata = PROVIDER_CATALOG.get(name, {}) or {}
        local = bool(metadata.get("local")) or name in LOCAL_PROVIDERS
        listed.append(
            {
                "name": name,
                "display_name": str(metadata.get("label") or metadata.get("name") or name),
                "default_model": str(DEFAULT_MODELS.get(name, "") or ""),
                "api_key_env": str(metadata.get("env", "") or ""),
                # A local runtime needs no key, so it is offered as the
                # zero-credential way to see the whole loop working.
                "needs_key": not local and bool(metadata.get("env")),
                "local": local,
            }
        )
    return {"ok": True, "providers": listed, "local_providers": list(LOCAL_PROVIDERS)}


def configure(provider: str, model: str = "") -> dict[str, Any]:
    """Record the provider and model choice, then re-report readiness.

    Only the route is written. `set_default_provider` can also take an inline
    API key and persist it to the global config; that argument is deliberately
    never passed from here, because a key typed into a browser form would end up
    in a file on disk.
    """
    from magent.config_ux import set_default_provider

    provider = (provider or "").strip()
    if not provider:
        raise ValueError("Choose a provider first.")

    result = set_default_provider(provider, (model or "").strip() or None)
    if not result.get("ok"):
        raise ValueError(str(result.get("error") or "That provider could not be selected."))

    state = readiness()
    state["configured"] = {"provider": result.get("provider"), "model": result.get("model")}
    return state
