"""Credential storage helpers.

MagAgent can keep credentials in config for portability, but this module adds
an optional OS keyring boundary for users who want secrets out of TOML.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SERVICE_NAME = "magent"


@dataclass
class AuthEntry:
    provider: str
    storage: str
    account: str
    configured: bool


def keyring_available() -> bool:
    try:
        import keyring  # noqa: F401

        return True
    except Exception:
        return False


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
    return {"ok": True, "provider": provider_id, "storage": "keyring", "account": keyring_account(provider_id)}


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
