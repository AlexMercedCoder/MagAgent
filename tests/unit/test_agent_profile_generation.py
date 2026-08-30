from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from magent.agent_profiles.generation import (
    GENERATION_CONTRACT,
    generate_profile_proposal,
    store_profile_proposal,
)
from magent.tools import ToolExecutor


class FakeProvider:
    display_name = "fake/reviewer"

    def __init__(self, responses: list[str]):
        self.responses = list(responses)

    async def complete(self, *_args, **_kwargs) -> str:
        return self.responses.pop(0)


def document(name: str = "accessibility-reviewer") -> dict:
    return {
        "oap": "1.0",
        "kind": "AgentProfile",
        "metadata": {
            "name": name,
            "description": "Use when reviewing user interfaces for accessibility.",
            "revision": 99,
            "trust": "managed",
        },
        "spec": {
            "role": {"instructions": "Review interfaces and explain accessibility findings."},
            "permissions": {"default": "ask", "edit": "deny", "shell": "deny"},
            "lifecycle": {"writeback": "auto"},
        },
        "state": {"facts": [{"id": "invented", "text": "A generated claim."}]},
        "history": [
            {
                "revision": 99,
                "at": "2026-01-01T00:00:00Z",
                "by": "model",
                "change": "invented",
                "sections": ["spec"],
            }
        ],
    }


@pytest.mark.asyncio
async def test_generation_is_validated_and_resets_authority_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "magent.agent_profiles.generation.profile_contract",
        lambda *_args, **_kwargs: {"schema": {}, "choices": {}},
    )
    monkeypatch.setattr(
        "magent.agent_profiles.generation.preview_profile",
        lambda value, **_kwargs: {
            "ok": True,
            "ready": True,
            "profile": {"name": value["metadata"]["name"]},
        },
    )
    result = await generate_profile_proposal(
        "Create an accessibility reviewer",
        project=tmp_path,
        config=SimpleNamespace(),
        provider=FakeProvider([json.dumps(document())]),
    )
    assert result["ok"] is True
    assert result["contract"] == GENERATION_CONTRACT
    assert result["document"]["metadata"]["revision"] == 1
    assert "trust" not in result["document"]["metadata"]
    assert result["document"]["state"] == {}
    assert result["document"]["history"] == []
    assert result["document"]["spec"]["lifecycle"]["writeback"] == "propose"


@pytest.mark.asyncio
async def test_generation_repairs_invalid_model_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "magent.agent_profiles.generation.profile_contract",
        lambda *_args, **_kwargs: {"schema": {}, "choices": {}},
    )
    monkeypatch.setattr(
        "magent.agent_profiles.generation.preview_profile",
        lambda value, **_kwargs: {"ok": True, "ready": True},
    )
    provider = FakeProvider(["not json", json.dumps(document("reviewer"))])
    result = await generate_profile_proposal(
        "Create a reviewer", project=tmp_path, config=SimpleNamespace(), provider=provider
    )
    assert result["ok"] is True
    assert result["document"]["metadata"]["name"] == "reviewer"


def test_autonomous_proposal_is_stored_outside_profile_roots(tmp_path: Path) -> None:
    stored = store_profile_proposal({"ok": True, "document": document()}, project=tmp_path)
    path = Path(stored["path"])
    assert path.parent == tmp_path / ".magent" / "profile-proposals"
    assert json.loads(path.read_text())["status"] == "pending"


@pytest.mark.asyncio
async def test_agent_tool_creates_reviewable_proposal_without_activating_profile(
    tmp_path: Path, monkeypatch
) -> None:
    async def fake_generate(*_args, **_kwargs) -> dict:
        return {"ok": True, "document": document(), "requires_review": True}

    monkeypatch.setattr("magent.agent_profiles.generation.generate_profile_proposal", fake_generate)
    executor = ToolExecutor(str(tmp_path), config=SimpleNamespace())

    result = await executor.dispatch(
        "create_agent_profile",
        {"prompt": "Create an accessibility specialist for a subagent"},
    )

    assert result["ok"] is True
    assert result["saved"] is False
    assert result["requires_review"] is True
    assert Path(result["proposal_path"]).is_file()
    assert not (tmp_path / ".magent" / "agents" / "accessibility-reviewer.yaml").exists()
