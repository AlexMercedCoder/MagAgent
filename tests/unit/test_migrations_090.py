from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent import config as magent_config
from magent.cli.main import app
from magent.migrations import (
    inspect_state_backup,
    migrate_state,
    migration_assurance_report,
    migration_plan,
    rollback_state,
)
from magent.state_schema import StateCompatibilityError, assert_supported_state, state_manifest


def legacy_state(root: Path) -> Path:
    profile = root / "users" / "alex" / "profile.toml"
    profile.parent.mkdir(parents=True)
    (root / "config.toml").write_text("[agent]\nmax_subagents = 5\n", encoding="utf-8")
    profile.write_text(
        '[permissions]\nallowed_commands = ["git *", "pytest *"]\n', encoding="utf-8"
    )
    return profile


def test_backup_first_migration_and_state_rollback(tmp_path: Path) -> None:
    profile = legacy_state(tmp_path)

    preview = migrate_state(tmp_path)
    result = migrate_state(tmp_path, apply=True)

    assert preview["status"] == "upgrade-ready"
    assert preview["applied"] is False
    assert result["ok"] is True
    assert result["applied"] is True
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600
    assert "max_subagents = 5" in (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "allowed_shell_patterns" in profile.read_text(encoding="utf-8")
    assert assert_supported_state(tmp_path)["schema_version"] == 1

    restored = rollback_state(tmp_path, result["backup"], apply=True)

    assert restored["ok"] is True
    assert "allowed_commands" in profile.read_text(encoding="utf-8")
    assert not (tmp_path / "state.json").exists()


def test_newer_state_refuses_downgrade(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text('{"schema_version": 99}', encoding="utf-8")

    plan = migration_plan(tmp_path)

    assert plan["ok"] is False
    assert plan["status"] == "downgrade-refused"
    with pytest.raises(StateCompatibilityError, match="newer"):
        assert_supported_state(tmp_path)


def test_backup_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "bad")

    with pytest.raises(StateCompatibilityError, match="Unsafe backup member"):
        inspect_state_backup(archive)


def test_state_marker_rejects_corrupt_and_invalid_payloads(tmp_path: Path) -> None:
    marker = tmp_path / "state.json"
    marker.write_text("{", encoding="utf-8")
    with pytest.raises(StateCompatibilityError, match="Could not read"):
        state_manifest(tmp_path)

    marker.write_text('{"schema_version": "new"}', encoding="utf-8")
    with pytest.raises(StateCompatibilityError, match="Invalid"):
        state_manifest(tmp_path)


def test_migration_assurance_covers_upgrade_rollback_and_refusal() -> None:
    report = migration_assurance_report()

    assert report["ok"] is True
    assert all(report["checks"].values())


def test_migration_history_never_contains_profile_values(tmp_path: Path) -> None:
    legacy_state(tmp_path)
    migrate_state(tmp_path, apply=True)

    history = json.loads((tmp_path / "migration-history.json").read_text(encoding="utf-8"))

    assert history[0]["changed"] == ["config.toml", "users/alex/profile.toml"]
    assert "pytest *" not in json.dumps(history)


def test_rollback_preview_and_missing_backup(tmp_path: Path) -> None:
    legacy_state(tmp_path)
    migrated = migrate_state(tmp_path, apply=True)

    preview = rollback_state(tmp_path, migrated["backup"])

    assert preview["ok"] is True
    assert preview["applied"] is False
    with pytest.raises(FileNotFoundError):
        inspect_state_backup(tmp_path / "missing.zip")


def test_config_loader_refuses_future_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(magent_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", tmp_path / "config.toml")
    (tmp_path / "state.json").write_text('{"schema_version": 99}', encoding="utf-8")

    with pytest.raises(StateCompatibilityError, match="Upgrade MagAgent"):
        magent_config.load_global_config()


def test_migration_cli_previews_then_applies(tmp_path: Path) -> None:
    legacy_state(tmp_path)
    runner = CliRunner()

    preview = runner.invoke(app, ["system", "migrate", "--root", str(tmp_path)])
    applied = runner.invoke(app, ["system", "migrate", "--root", str(tmp_path), "--apply"])

    assert preview.exit_code == 0
    assert json.loads(preview.output)["status"] == "upgrade-ready"
    assert applied.exit_code == 0
    assert json.loads(applied.output)["applied"] is True
