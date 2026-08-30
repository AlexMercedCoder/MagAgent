from __future__ import annotations

from types import SimpleNamespace

import magent.web_chat as web_chat
from magent.web_chat import WebChatRunner


class FakeSession:
    created: list[FakeSession] = []

    def __init__(self, **kwargs):
        self.profile = kwargs.get("profile")
        self.config = kwargs.get("config")
        self.session_id = f"session-{len(self.created) + 1}"
        self.conversation = []
        self.ended = False
        self.created.append(self)

    async def stream_chat(self, prompt: str):
        name = self.profile.name if self.profile else "MagAgent"
        yield f"{name}:"
        yield prompt[-20:]

    async def end_session(self):
        self.ended = True


def _patch_runtime(monkeypatch):
    FakeSession.created = []
    config = SimpleNamespace(_user={}, _global={})
    monkeypatch.setattr(web_chat, "load_config", lambda _username: config)
    monkeypatch.setattr(
        web_chat,
        "build_provider",
        lambda _config, provider, model: SimpleNamespace(
            provider_id=provider or "fake", model=model or "fake-model"
        ),
    )
    monkeypatch.setattr(web_chat, "build_extraction_provider", lambda _config: object())
    monkeypatch.setattr(web_chat, "AgentSession", FakeSession)
    monkeypatch.setattr(
        WebChatRunner,
        "_profile",
        lambda self, name, config: SimpleNamespace(
            name=name,
            provider="fake",
            model=f"{name}-model",
            resolved=SimpleNamespace(revision=2),
        ),
    )


def test_web_chat_runner_streams_normal_profile_turn(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    chunks = []
    result = WebChatRunner("alex", ".").run(
        {"kind": "bot", "profiles": ["review"], "messages": []},
        "Please review this change",
        on_chunk=lambda speaker, text: chunks.append((speaker, text)),
    )

    assert result[0]["speaker"] == "review"
    assert result[0]["model"] == "review-model"
    assert chunks[0] == ("review", "review:")
    assert all(session.ended for session in FakeSession.created)


def test_web_chat_runner_bounds_group_and_adds_coordinator_synthesis(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    result = WebChatRunner("alex", ".").run(
        {
            "kind": "group",
            "profiles": ["review", "docs", "explore"],
            "coordinator": "review",
            "messages": [],
        },
        "Prepare the release",
    )

    assert [item["speaker"] for item in result] == [
        "review",
        "docs",
        "explore",
        "review · synthesis",
    ]
    assert len(FakeSession.created) == 4
    assert all(session.ended for session in FakeSession.created)


def test_web_chat_runner_applies_permission_mode_without_persisting(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    result = WebChatRunner("alex", ".", permission_mode="paranoid").run(
        {"kind": "chat", "profiles": [], "messages": []},
        "Inspect safely",
    )

    assert result[0]["speaker"] == "MagAgent"
    assert FakeSession.created[0].config._user["permissions"]["mode"] == "paranoid"
