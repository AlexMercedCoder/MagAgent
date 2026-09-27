"""Credential storage helpers.

MagAgent can keep credentials in config for portability, but this module adds
an optional OS keyring boundary for users who want secrets out of TOML.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVICE_NAME = "magent"


@dataclass
class AuthEntry:
    provider: str
    storage: str
    account: str
    configured: bool


KEYRING_INSTALL_HINT = (
    "Install the optional keyring support with `pip install 'mag-agent[keyring]'` "
    "(or `pipx inject mag-agent keyring`), or rerun with --storage config to keep the key "
    "in config.toml (mode 0600)."
)


def keyring_status() -> dict[str, Any]:
    """Whether an OS credential store is usable, and what to do if not.

    The `keyring` package is an optional extra (`mag-agent[keyring]`). Even when
    it is installed, a machine with no credential service (for example a Linux
    server without a Secret Service daemon) only has keyring's "fail" backend.
    """

    try:
        import keyring
    except Exception:
        return {"available": False, "backend": "", "hint": KEYRING_INSTALL_HINT}
    try:
        backend = keyring.get_keyring()
    except Exception as exc:  # pragma: no cover - backend discovery failure
        return {"available": False, "backend": "", "hint": f"keyring is unusable: {exc}"}
    name = f"{type(backend).__module__}.{type(backend).__name__}"
    priority = getattr(backend, "priority", 1)
    try:
        usable = float(priority) > 0 and "fail" not in name.lower()
    except (TypeError, ValueError):
        usable = "fail" not in name.lower()
    status: dict[str, Any] = {"available": usable, "backend": name}
    if not usable:
        status["hint"] = (
            "keyring is installed but no OS credential store is running (backend "
            f"{name}). Start one (Secret Service, macOS Keychain, Windows Credential Manager) "
            "or rerun with --storage config."
        )
    return status


def keyring_available() -> bool:
    return bool(keyring_status()["available"])


def keyring_account(provider_id: str) -> str:
    return f"provider:{provider_id}"


def save_keyring_secret(provider_id: str, value: str) -> dict[str, Any]:
    if not value:
        return {"ok": False, "error": "secret value is required"}
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, keyring_account(provider_id), value)
    except Exception as exc:
        return {"ok": False, "error": f"keyring save failed: {exc}"}
    return {
        "ok": True,
        "provider": provider_id,
        "storage": "keyring",
        "account": keyring_account(provider_id),
    }


def load_keyring_secret(provider_id: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, keyring_account(provider_id))
    except Exception:
        return None


def delete_keyring_secret(provider_id: str) -> dict[str, Any]:
    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, keyring_account(provider_id))
        return {"ok": True, "provider": provider_id, "deleted": True}
    except Exception as exc:
        text = str(exc).lower()
        if "no entry" in text or "not found" in text:
            return {"ok": True, "provider": provider_id, "deleted": False}
        return {"ok": False, "provider": provider_id, "error": f"keyring delete failed: {exc}"}


def list_auth_entries(providers: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider_id, cfg in sorted(providers.items()):
        if not isinstance(cfg, dict):
            continue
        storage = "none"
        configured = False
        account = ""
        if cfg.get("api_key"):
            storage = "config"
            configured = True
        elif cfg.get("api_key_env"):
            storage = "env"
            account = str(cfg.get("api_key_env"))
            configured = True
        elif cfg.get("api_key_keyring"):
            storage = "keyring"
            account = str(cfg.get("api_key_keyring"))
            configured = load_keyring_secret(provider_id) is not None
        rows.append(
            {
                "provider": provider_id,
                "storage": storage,
                "account": account,
                "configured": configured,
            }
        )
    return rows


def store_provider_secret(
    provider_id: str, secret: str, *, storage: str = "keyring"
) -> dict[str, Any]:
    """Store a provider key and point the global config at it.

    ``keyring`` keeps the value in the OS credential store and records only the
    account name in config. ``config`` writes it to ``config.toml`` and tightens
    the file to 0600. The returned dict never contains the secret.
    """
    from magent.config import GLOBAL_CONFIG, load_global_config, save_global_config

    if storage not in {"keyring", "config"}:
        return {"ok": False, "provider": provider_id, "error": "storage must be keyring or config"}
    if not secret:
        return {"ok": False, "provider": provider_id, "error": "secret value is required"}
    if storage == "keyring":
        status = keyring_status()
        if not status["available"]:
            return {
                "ok": False,
                "provider": provider_id,
                "storage": "keyring",
                "error": "No usable OS keyring is available to this Python environment.",
                "hint": status.get("hint", KEYRING_INSTALL_HINT),
            }
        result = save_keyring_secret(provider_id, secret)
        if not result.get("ok"):
            return {
                **result,
                "provider": provider_id,
                "storage": "keyring",
                "hint": "Rerun with --storage config to keep the key in config.toml (mode 0600).",
            }
    cfg = load_global_config()
    entry = cfg.setdefault("providers", {}).setdefault(provider_id, {})
    if storage == "keyring":
        entry.pop("api_key", None)
        entry["api_key_keyring"] = keyring_account(provider_id)
    else:
        entry.pop("api_key_keyring", None)
        entry["api_key"] = secret
    save_global_config(cfg)
    path = Path(GLOBAL_CONFIG)
    if storage == "config":
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    payload: dict[str, Any] = {"ok": True, "provider": provider_id, "storage": storage}
    if storage == "keyring":
        payload["account"] = keyring_account(provider_id)
    else:
        payload["config_path"] = str(path)
    return payload
