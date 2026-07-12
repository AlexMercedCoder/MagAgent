from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from magent.artifact_contracts import infer_expected_artifacts, verify_expected_artifacts
from magent.command_policy import command_policy
from magent.diagnostics import deep_diagnostics
from magent.permission_ux import permission_apply_profile, permission_profiles


def test_artifact_contract_detects_missing_and_placeholder(tmp_path: Path) -> None:
    (tmp_path / "cheese.html").write_text("cheese.html", encoding="utf-8")
    paths = infer_expected_artifacts("create cheese.html and oranges.html", cwd=tmp_path)

    audit = verify_expected_artifacts(paths)

    assert len(paths) == 2
    assert audit["ok"] is False
    assert {item["reason"] for item in audit["failed"]} >= {"placeholder content", "missing"}


def test_command_policy_blocks_tier_three_commands() -> None:
    policy = command_policy("rm -rf /tmp/demo")

    assert policy["ok"] is False
    assert policy["blocked"] is True


def test_permission_profiles_apply(tmp_path: Path, monkeypatch) -> None:
    from magent import config as magent_config

    monkeypatch.setattr(magent_config, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", tmp_path / "users" / "current")
    magent_config.create_user("alex")

    result = permission_apply_profile("alex", "coding")

    assert result["ok"] is True
    assert permission_profiles()["profiles"]["coding"]["mode"] == "balanced"


def test_deep_diagnostics_reports_provider_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    from magent import diagnostics

    monkeypatch.setattr(diagnostics, "provider_matrix", lambda: {"providers": [{"id": "fake", "ready": True}]})
    config = SimpleNamespace(default_provider="fake", get=lambda *args, **kwargs: {})
    store = SimpleNamespace(read=lambda *_args, **_kwargs: [])

    result = deep_diagnostics("alex", config, store, project=tmp_path, prompt="create missing.html")

    assert result["ok"] is False
    assert any(item["key"] == "artifact_contract" for item in result["checks"])
