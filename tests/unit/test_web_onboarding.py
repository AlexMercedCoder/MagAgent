"""First-run readiness for the Web UI.

The browser assumed a provider was already configured: open `magent ui` on a
machine that never ran `magent setup` and the first message failed with a
credential error, having never said that no provider was chosen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from magent import config as magent_config
from magent import web_onboarding


@pytest.fixture
def isolated(monkeypatch, tmp_path: Path) -> Path:
    """A machine that has never been configured."""
    config_dir = tmp_path / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", config_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", config_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", config_dir / "users" / "current")
    return config_dir


def test_an_unconfigured_machine_is_not_ready(isolated: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_onboarding, "_default_provider", lambda: ("", ""))

    state = web_onboarding.readiness()
    assert state["ready"] is False
    assert "provider" in state["blocking"]


def test_readiness_names_every_step(isolated: Path) -> None:
    steps = {step["id"] for step in web_onboarding.readiness()["steps"]}
    assert steps == {"provider", "model", "credential", "workspace"}


def test_a_running_local_provider_makes_a_machine_usable(isolated: Path, monkeypatch) -> None:
    """A first run must be possible with no credential at all."""
    monkeypatch.setattr(web_onboarding, "_local_reachable", lambda *_: (True, "ollama is running"))
    state = web_onboarding.configure("ollama")

    assert state["ready"] is True
    assert state["local"] is True
    assert state["blocking"] == []


def test_a_local_provider_that_is_not_running_blocks(isolated: Path, monkeypatch) -> None:
    """The shipped default is `ollama`, and naming it is not the same as running it.

    `provider_readiness` calls any local provider ready because it needs no key,
    so a machine that had never installed Ollama reported ready and then failed
    on the first message with a connection error.
    """
    monkeypatch.setattr(
        web_onboarding, "_local_reachable", lambda *_: (False, "ollama is not answering")
    )
    state = web_onboarding.configure("ollama")

    assert state["ready"] is False
    assert state["blocking"] == ["credential"]
    credential = next(step for step in state["steps"] if step["id"] == "credential")
    assert "not answering" in credential["detail"]
    # The remedy has to be reachable from here, not only from a terminal.
    assert "hosted provider" in credential["action"]


def test_the_local_probe_treats_any_failure_as_not_running(monkeypatch) -> None:
    import httpx

    def refuse(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", refuse)
    running, detail = web_onboarding._local_reachable("ollama", "http://localhost:11434")

    assert running is False
    assert "http://localhost:11434" in detail


def test_the_local_probe_fails_fast(monkeypatch) -> None:
    """It runs on every boot, so it must not make the browser wait."""
    import httpx

    seen: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

    def record(url, **kwargs):
        seen["url"] = url
        seen["timeout"] = kwargs.get("timeout")
        return Response()

    monkeypatch.setattr(httpx, "get", record)
    running, _ = web_onboarding._local_reachable("ollama", "http://localhost:11434")

    assert running is True
    assert seen["url"] == "http://localhost:11434/api/tags"
    assert seen["timeout"] == web_onboarding.LOCAL_PROBE_TIMEOUT_SECONDS


def test_a_hosted_provider_without_a_key_is_blocked_on_the_credential(
    isolated: Path, monkeypatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    state = web_onboarding.configure("openai")

    assert state["ready"] is False
    assert state["blocking"] == ["credential"]
    credential = next(step for step in state["steps"] if step["id"] == "credential")
    # The step must name the variable, or the user has to go hunting.
    assert credential["env"] == "OPENAI_API_KEY"


def test_a_key_in_the_environment_clears_the_block(isolated: Path, monkeypatch) -> None:
    web_onboarding.configure("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")

    state = web_onboarding.readiness()
    assert state["ready"] is True
    assert state["blocking"] == []


def test_the_model_step_never_blocks(isolated: Path, monkeypatch) -> None:
    """A provider without an explicit model still has a catalog default."""
    monkeypatch.setattr(web_onboarding, "_default_provider", lambda: ("ollama", ""))
    monkeypatch.setattr(web_onboarding, "_local_reachable", lambda *_: (True, "running"))

    state = web_onboarding.readiness()
    model = next(step for step in state["steps"] if step["id"] == "model")
    assert model["ok"] is True
    assert "model" not in state["blocking"]


def test_configure_records_the_chosen_model(isolated: Path) -> None:
    state = web_onboarding.configure("openai", "gpt-4o-mini")

    assert state["configured"] == {"provider": "openai", "model": "gpt-4o-mini"}
    assert state["model"] == "gpt-4o-mini"


def test_configure_falls_back_to_the_catalog_default_model(isolated: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_onboarding, "_local_reachable", lambda *_: (True, "running"))
    state = web_onboarding.configure("ollama")
    assert state["model"]


def test_configure_never_writes_a_credential(isolated: Path) -> None:
    """set_default_provider accepts an inline key; this path must not pass one."""
    web_onboarding.configure("openai", "gpt-4o-mini")
    written = magent_config.GLOBAL_CONFIG.read_text(encoding="utf-8")

    assert "openai" in written
    # `api_key_env` names where a key lives and is not itself a secret; an
    # `api_key` entry would be the actual credential on disk.
    assert "api_key =" not in written
    assert 'api_key"' not in written


@pytest.mark.parametrize("bad", ["", "   "])
def test_an_empty_provider_is_refused(isolated: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="Choose a provider"):
        web_onboarding.configure(bad)


def test_an_unknown_provider_is_refused_with_its_reason(isolated: Path) -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        web_onboarding.configure("nonesuch-provider")


def test_providers_are_listed_with_their_key_variable(isolated: Path) -> None:
    listed = web_onboarding.providers()
    by_name = {item["name"]: item for item in listed["providers"]}

    assert by_name["openai"]["needs_key"] is True
    assert by_name["openai"]["api_key_env"] == "OPENAI_API_KEY"
    assert by_name["ollama"]["needs_key"] is False
    assert by_name["ollama"]["local"] is True
    assert "default_provider" in listed and "default_model" in listed
    assert any(item["value"] == "openai/gpt-image-1" for item in listed["image_models"])


def test_configure_can_explicitly_store_a_key_in_protected_config(isolated: Path) -> None:
    state = web_onboarding.configure(
        "openai", "gpt-4o-mini", credential="test-secret", credential_storage="config"
    )

    assert state["credential_storage"] == "config"
    assert "test-secret" in magent_config.GLOBAL_CONFIG.read_text(encoding="utf-8")
    assert magent_config.GLOBAL_CONFIG.stat().st_mode & 0o777 == 0o600


def test_configure_prefers_keyring_for_a_supplied_key(isolated: Path, monkeypatch) -> None:
    from magent import auth_store

    saved: dict[str, str] = {}
    monkeypatch.setattr(
        auth_store,
        "save_keyring_secret",
        lambda provider, secret: saved.update(provider=provider, secret=secret) or {"ok": True},
    )
    monkeypatch.setattr(auth_store, "keyring_account", lambda provider: f"magent:{provider}")
    monkeypatch.setattr(web_onboarding, "readiness", lambda: {"ok": True, "ready": True})

    state = web_onboarding.configure("openai", credential="test-secret")

    assert saved == {"provider": "openai", "secret": "test-secret"}
    assert state["credential_storage"] == "keyring"
    written = magent_config.GLOBAL_CONFIG.read_text(encoding="utf-8")
    assert "test-secret" not in written
    assert "magent:openai" in written


def test_at_least_one_listed_provider_needs_no_key(isolated: Path) -> None:
    """Otherwise the panel offers no way to start without hunting for a key."""
    listed = web_onboarding.providers()
    assert any(not item["needs_key"] for item in listed["providers"])


def test_the_reason_names_the_thing_that_is_actually_wrong(isolated: Path, monkeypatch) -> None:
    """The panel claimed "no provider is configured" while the provider step
    showed a tick and the real problem was a local runtime that was not up."""
    monkeypatch.setattr(
        web_onboarding, "_local_reachable", lambda *_: (False, "ollama is not answering")
    )
    state = web_onboarding.configure("ollama")

    assert "not answering" in state["reason"]
    assert "No provider is configured" not in state["reason"]


def test_the_reason_says_so_when_no_provider_is_chosen(isolated: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_onboarding, "_default_provider", lambda: ("", ""))
    assert "No provider is configured" in web_onboarding.readiness()["reason"]


def test_a_ready_machine_carries_no_reason(isolated: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_onboarding, "_local_reachable", lambda *_: (True, "running"))
    assert web_onboarding.configure("ollama")["reason"] == ""


def test_a_local_provider_step_is_labelled_for_its_runtime(isolated: Path, monkeypatch) -> None:
    """ "Credential" is the wrong word for a runtime that needs no key."""
    monkeypatch.setattr(web_onboarding, "_local_reachable", lambda *_: (False, "not answering"))
    state = web_onboarding.configure("ollama")

    credential = next(step for step in state["steps"] if step["id"] == "credential")
    assert credential["label"] == "Local runtime"


def test_a_hosted_provider_step_keeps_the_credential_label(isolated: Path) -> None:
    state = web_onboarding.configure("openai")
    credential = next(step for step in state["steps"] if step["id"] == "credential")
    assert credential["label"] == "Credential"
