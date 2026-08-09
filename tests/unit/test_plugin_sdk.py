from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent import config as magent_config
from magent import plugins
from magent.cli import main as cli_main
from magent.plugin_sdk import build_registry_index, plugin_digest, validate_plugin, verify_plugin

runner = CliRunner()


def make_plugin(root: Path, *, checksum: str = "") -> Path:
    root.mkdir()
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    checksum_line = f'checksum = "{checksum}"\n' if checksum else ""
    (root / "magent-plugin.toml").write_text(
        "[plugin]\n"
        'name = "demo"\nversion = "1.0.0"\napi_version = "1"\n'
        'capabilities = ["skills"]\npermissions = []\ntrust = "reviewed"\n'
        + checksum_line,
        encoding="utf-8",
    )
    return root


def redirect_plugins(monkeypatch, root: Path) -> None:
    config = root / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", config)
    monkeypatch.setattr(plugins, "PLUGIN_DIR", config / "plugins")
    monkeypatch.setattr(plugins, "PLUGIN_STATE", config / "plugins.toml")


def test_plugin_conformance_and_digest_are_deterministic(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "demo")
    first = validate_plugin(plugin)
    second = plugin_digest(plugin)

    assert first["ok"] is True
    assert first["digest"] == second
    assert first["contributions"]["skills"] == ["skills/demo/SKILL.md"]
    assert "Plugin is unsigned" in first["warnings"]


def test_plugin_checksum_detects_tampering(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "demo")
    digest = plugin_digest(plugin)
    make_manifest = (plugin / "magent-plugin.toml").read_text(encoding="utf-8")
    (plugin / "magent-plugin.toml").write_text(make_manifest + f'checksum = "{digest}"\n', encoding="utf-8")
    assert verify_plugin(plugin)["integrity"] == "verified"

    (plugin / "skills" / "demo" / "SKILL.md").write_text("# Changed\n", encoding="utf-8")
    result = verify_plugin(plugin)
    assert result["ok"] is False
    assert "Checksum mismatch" in result["errors"][0]


def test_plugin_rejects_unknown_permissions_and_invalid_mcp(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "demo")
    manifest = (plugin / "magent-plugin.toml").read_text(encoding="utf-8")
    (plugin / "magent-plugin.toml").write_text(manifest.replace("permissions = []", 'permissions = ["root"]'), encoding="utf-8")
    (plugin / "mcp.toml").write_text("[mcp]\n", encoding="utf-8")
    result = validate_plugin(plugin)
    assert result["ok"] is False
    assert any("Unknown permissions" in item for item in result["errors"])
    assert any("at least one" in item for item in result["errors"])


def test_registry_index_contains_compatibility_and_integrity_metadata(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "demo")
    index = build_registry_index([plugin])
    assert index["schema"] == "magent.plugin-registry.v1"
    assert index["plugins"][0]["name"] == "demo"
    assert index["plugins"][0]["digest"].startswith("sha256:")


def test_plugin_project_grants_and_cli_contract(tmp_path: Path, monkeypatch) -> None:
    redirect_plugins(monkeypatch, tmp_path)
    source = make_plugin(tmp_path / "source")
    installed = plugins.install_plugin(source, name="demo")
    granted = plugins.set_plugin_grant("demo", scope="project", permissions=["files"], project=str(tmp_path))
    listed = plugins.list_plugins()
    cli = runner.invoke(cli_main.app, ["plugin", "verify", installed["path"]])

    assert installed["ok"] is True
    assert granted["ok"] is True
    assert listed["plugins"][0]["grants"][str(tmp_path.resolve())] == ["files"]
    assert cli.exit_code == 0
    assert json.loads(cli.output)["integrity"] == "verified"
