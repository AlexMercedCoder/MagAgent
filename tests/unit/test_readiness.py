from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import magent.readiness as readiness_module
from magent.readiness import readiness_report


class Store:
    def __init__(self):
        self.data = {}

    def read(self, name, default):
        return self.data.get(name, default)

    def write(self, name, data):
        self.data[name] = data


def test_readiness_report_combines_local_checks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        readiness_module,
        "provider_matrix",
        lambda: {"providers": [{"id": "openai", "ready": True, "configured": True}]},
    )
    monkeypatch.setattr(readiness_module, "docs_doctor", lambda: {"ok": True})
    monkeypatch.setattr(readiness_module, "project_doctor", lambda root, store: {"ok": True})
    monkeypatch.setattr(readiness_module, "doctor_actions", lambda username: {"ok": True})

    config = SimpleNamespace(
        default_provider="openai",
        default_model="gpt",
        provider_config=lambda provider: {"default_model": "gpt"},
    )
    result = readiness_report("alice", config, Store(), project=tmp_path)

    assert result["ok"] is True
    assert result["provider"] == "openai"
    assert any(check["key"] == "docs" for check in result["checks"])
