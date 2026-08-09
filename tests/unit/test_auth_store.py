from __future__ import annotations

import sys
from types import SimpleNamespace

from magent import auth_store


def test_keyring_availability_and_account(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace())

    assert auth_store.keyring_available() is True
    assert auth_store.keyring_account("openai") == "provider:openai"

    monkeypatch.setitem(sys.modules, "keyring", None)
    assert auth_store.keyring_available() is False


def test_keyring_secret_lifecycle(monkeypatch) -> None:
    saved: dict[tuple[str, str], str] = {}

    def set_password(service: str, account: str, value: str) -> None:
        saved[(service, account)] = value

    def get_password(service: str, account: str) -> str | None:
        return saved.get((service, account))

    def delete_password(service: str, account: str) -> None:
        del saved[(service, account)]

    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(
            set_password=set_password,
            get_password=get_password,
            delete_password=delete_password,
        ),
    )

    assert auth_store.save_keyring_secret("openai", "") == {
        "ok": False,
        "error": "secret value is required",
    }
    result = auth_store.save_keyring_secret("openai", "secret")
    assert result["ok"] is True
    assert result["account"] == "provider:openai"
    assert auth_store.load_keyring_secret("openai") == "secret"
    assert auth_store.delete_keyring_secret("openai")["deleted"] is True


def test_keyring_failures_are_safe_and_redacted(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setitem(
        sys.modules,
        "keyring",
        SimpleNamespace(set_password=fail, get_password=fail, delete_password=fail),
    )

    assert auth_store.save_keyring_secret("openai", "secret")["ok"] is False
    assert auth_store.load_keyring_secret("openai") is None
    deleted = auth_store.delete_keyring_secret("openai")
    assert deleted["ok"] is False
    assert "backend unavailable" in deleted["error"]


def test_keyring_missing_entry_is_not_an_error(monkeypatch) -> None:
    def missing(*args, **kwargs):
        raise RuntimeError("No entry found")

    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(delete_password=missing))

    assert auth_store.delete_keyring_secret("openai") == {
        "ok": True,
        "provider": "openai",
        "deleted": False,
    }


def test_list_auth_entries_reports_storage_and_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_store,
        "load_keyring_secret",
        lambda provider_id: "stored" if provider_id == "anthropic" else None,
    )

    rows = auth_store.list_auth_entries(
        {
            "openai": {"api_key": "inline"},
            "openrouter": {"api_key_env": "OPENROUTER_API_KEY"},
            "anthropic": {"api_key_keyring": "provider:anthropic"},
            "gemini": {"api_key_keyring": "provider:gemini"},
            "ollama": {},
            "invalid": "ignored",
        }
    )

    by_provider = {row["provider"]: row for row in rows}
    assert "invalid" not in by_provider
    assert by_provider["openai"]["storage"] == "config"
    assert by_provider["openrouter"]["account"] == "OPENROUTER_API_KEY"
    assert by_provider["anthropic"]["configured"] is True
    assert by_provider["gemini"]["configured"] is False
    assert by_provider["ollama"]["storage"] == "none"
