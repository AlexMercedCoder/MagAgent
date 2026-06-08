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
