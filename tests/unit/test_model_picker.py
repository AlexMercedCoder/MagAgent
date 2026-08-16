from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from magent.cli import model_picker


def test_picker_searches_live_models(monkeypatch) -> None:
    monkeypatch.setattr(
        model_picker,
        "discover_provider_models",
        lambda *_args, **_kwargs: {
            "ok": True,
            "source": "live",
            "models": ["gpt-5-mini", "claude-sonnet-5", "text-embedding-3-small"],
        },
    )
    answers = iter(["/claude", "1"])
    monkeypatch.setattr(
        model_picker.Prompt,
        "ask",
        lambda *_args, **_kwargs: next(answers),
    )

    selected = model_picker.prompt_for_provider_model(
        SimpleNamespace(),
        SimpleNamespace(),
        "openrouter",
        default_model="gpt-5-mini",
        console=Console(file=StringIO()),
    )

    assert selected == "claude-sonnet-5"


def test_picker_allows_manual_model_when_discovery_falls_back(monkeypatch) -> None:
    monkeypatch.setattr(
        model_picker,
        "discover_provider_models",
        lambda *_args, **_kwargs: {
            "ok": True,
            "source": "catalog",
            "models": ["gpt-5"],
            "warning": "offline",
        },
    )
    monkeypatch.setattr(
        model_picker.Prompt,
        "ask",
        lambda *_args, **_kwargs: "private-model-v2",
    )

    selected = model_picker.prompt_for_provider_model(
        SimpleNamespace(),
        SimpleNamespace(),
        "openai",
        default_model="gpt-5",
        console=Console(file=StringIO()),
    )

    assert selected == "private-model-v2"
