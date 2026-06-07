from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import magent.provider_smoke as provider_smoke
from magent.provider_smoke import run_provider_tool_smoke


class Store:
    def __init__(self):
        self.data = {}

    def read(self, name, default):
        return self.data.get(name, default)

    def write(self, name, data):
        self.data[name] = data


class SlowSession:
    def __init__(self, **kwargs):
        self.cwd = kwargs["cwd"]
        self.scratchpad = {"files_touched": []}

    async def chat(self, prompt: str) -> str:
        await asyncio.sleep(1)
        return "late"

    async def end_session(self) -> None:
        return None


def test_provider_tool_smoke_times_out(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(provider_smoke, "AgentSession", SlowSession)
    monkeypatch.setattr(
        provider_smoke,
        "build_provider",
        lambda config, provider, model: SimpleNamespace(model=model or "model"),
    )
    monkeypatch.setattr(
        provider_smoke,
        "build_extraction_provider",
        lambda config: SimpleNamespace(model="extract"),
    )

    result = run_provider_tool_smoke(
        "alice",
        SimpleNamespace(),
        Store(),
        "test-provider",
        project=tmp_path,
        timeout_seconds=0,
    )

    assert result["ok"] is False
    assert "timed out" in result["error"]
