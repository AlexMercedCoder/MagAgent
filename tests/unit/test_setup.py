from __future__ import annotations

from types import SimpleNamespace

import magent.providers as providers
from magent import setup


def test_setup_smoke_test_uses_asyncio_run(monkeypatch) -> None:
    calls: list[str] = []

    def fail_if_get_event_loop():
        raise AssertionError("get_event_loop should not be used by setup smoke tests")

    async def fake_test_provider(provider):
        calls.append(provider.model)
        return True

    monkeypatch.setattr(setup.asyncio, "get_event_loop", fail_if_get_event_loop)
    monkeypatch.setattr(
        providers,
        "build_provider",
        lambda provider_id, model, api_key, p_cfg: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(providers, "test_provider", fake_test_provider)

    setup._smoke_test("opencode-go", "deepseek-v4-flash", None, None, "secret")

    assert calls == ["deepseek-v4-flash"]


def test_get_api_key_skips_credentials_for_local_providers() -> None:
    assert setup._get_api_key("ollama") == (None, None)
    assert setup._get_api_key("lmstudio") == (None, None)
    assert setup._get_api_key("custom") == (None, None)


def test_get_api_key_uses_existing_environment(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "configured")

    assert setup._get_api_key("gemini") == ("GEMINI_API_KEY", None)


def test_get_api_key_can_store_inline_secret(monkeypatch) -> None:
    answers = iter(["1", "secret-value"])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(setup.Prompt, "ask", lambda *args, **kwargs: next(answers))

    assert setup._get_api_key("openai") == (None, "secret-value")


def test_get_api_key_can_choose_environment_name(monkeypatch) -> None:
    answers = iter(["2", "MY_OPENAI_KEY"])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(setup.Prompt, "ask", lambda *args, **kwargs: next(answers))

    assert setup._get_api_key("openai") == ("MY_OPENAI_KEY", None)


def test_get_api_key_skip_returns_provider_default(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(setup.Prompt, "ask", lambda *args, **kwargs: "3")

    assert setup._get_api_key("anthropic") == ("ANTHROPIC_API_KEY", None)


def test_prompt_create_user_normalizes_and_creates(monkeypatch) -> None:
    created: list[str] = []
    current: list[str] = []
    answers = iter(["", "Alex Merced"])
    monkeypatch.setattr(setup.Prompt, "ask", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(setup, "user_exists", lambda username: False)
    monkeypatch.setattr(setup, "create_user", created.append)
    monkeypatch.setattr(setup, "set_current_user", current.append)

    assert setup._prompt_create_user() == "alex_merced"
    assert created == ["alex_merced"]
    assert current == ["alex_merced"]


def test_prompt_create_user_switches_to_existing(monkeypatch) -> None:
    current: list[str] = []
    monkeypatch.setattr(setup.Prompt, "ask", lambda *args, **kwargs: "Alice")
    monkeypatch.setattr(setup, "user_exists", lambda username: True)
    monkeypatch.setattr(setup, "set_current_user", current.append)

    assert setup._prompt_create_user() == "alice"
    assert current == ["alice"]


def test_smoke_test_reports_provider_failure(monkeypatch) -> None:
    async def fake_test_provider(provider):
        return False

    monkeypatch.setattr(
        providers,
        "build_provider",
        lambda provider_id, model, api_key, p_cfg: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(providers, "test_provider", fake_test_provider)

    setup._smoke_test("openai", "gpt-test", None, None, "secret")


def test_smoke_test_handles_provider_exception(monkeypatch) -> None:
    async def fake_test_provider(provider):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        providers,
        "build_provider",
        lambda provider_id, model, api_key, p_cfg: SimpleNamespace(model=model),
    )
    monkeypatch.setattr(providers, "test_provider", fake_test_provider)

    setup._smoke_test("openai", "gpt-test", None, None, "secret")
