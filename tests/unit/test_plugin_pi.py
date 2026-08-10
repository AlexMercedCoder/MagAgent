from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent import plugins
from magent.cli import main as cli_main
from magent.plugin_sdk import validate_plugin

runner = CliRunner()


def _redirect_plugins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(plugins, "PLUGIN_DIR", tmp_path / "installed")
    monkeypatch.setattr(plugins, "PLUGIN_STATE", tmp_path / "plugins.toml")


def _pi_package(tmp_path: Path) -> Path:
    source = tmp_path / "pi-package"
    (source / "skills" / "review").mkdir(parents=True)
    (source / "prompts").mkdir()
    (source / "extensions").mkdir()
    (source / "themes").mkdir()
    (source / "skills" / "review" / "SKILL.md").write_text("# Review\nCheck the patch.\n", encoding="utf-8")
    (source / "prompts" / "release.md").write_text("Prepare {{version}}.\n", encoding="utf-8")
    (source / "extensions" / "tools.ts").write_text("export default function (pi) {}\n", encoding="utf-8")
    (source / "themes" / "mag.json").write_text('{"name":"mag"}\n', encoding="utf-8")
    (source / "AGENTS.md").write_text("Use project conventions.\n", encoding="utf-8")
    (source / "mcp.json").write_text(
        json.dumps({"mcpServers": {"demo": {"command": "demo-server", "args": []}}}),
        encoding="utf-8",
    )
    (source / "package.json").write_text(
        json.dumps(
            {
                "name": "@demo/pi-pack",
                "version": "1.2.0",
                "keywords": ["pi-package"],
                "pi": {
                    "extensions": ["./extensions/tools.ts"],
                    "skills": ["./skills"],
                    "prompts": ["./prompts"],
                    "themes": ["./themes/mag.json"],
                },
            }
        ),
        encoding="utf-8",
    )
    return source


def test_pi_import_converts_portable_assets_and_quarantines_extensions(tmp_path: Path, monkeypatch) -> None:
    _redirect_plugins(monkeypatch, tmp_path)
    source = _pi_package(tmp_path)

    result = plugins.import_compat_plugin("pi", source, name="pi-pack")

    assert result["ok"] is True
    assert result["converted"]["agents"]
    assert result["converted"]["skills"] == ["skills/review/SKILL.md"]
    assert result["converted"]["recipes"] == ["recipes/pi-release.md"]
    assert result["converted"]["mcp"] == ["demo"]
    report = result["compatibility_report"]
    assert report["portable"]["mcp"] == ["demo"]
    assert report["preserved"]["extensions"] == ["extensions/tools.ts"]
    assert report["runtime"]["native_extension_execution"] is False
    installed = Path(result["path"])
    assert (installed / "compatibility/pi/package/extensions/tools.ts").is_file()
    assert not (installed / "tools.ts").exists()
    validation = validate_plugin(installed, strict=True)
    assert validation["ok"] is True, validation["errors"]
    assert "external_process" in validation["manifest"]["permissions"]


def test_pi_import_rejects_manifest_paths_outside_package(tmp_path: Path, monkeypatch) -> None:
    _redirect_plugins(monkeypatch, tmp_path)
    source = _pi_package(tmp_path)
    data = json.loads((source / "package.json").read_text(encoding="utf-8"))
    data["pi"]["extensions"] = ["../outside.ts"]
    (source / "package.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "outside.ts").write_text("do not import\n", encoding="utf-8")

    result = plugins.import_compat_plugin("pi", source, name="bounded-pi")

    assert result["ok"] is True
    assert result["compatibility_report"]["preserved"]["extensions"] == []


def test_pi_bridge_requires_enablement_and_explicit_process_grant(tmp_path: Path, monkeypatch) -> None:
    _redirect_plugins(monkeypatch, tmp_path)
    source = _pi_package(tmp_path)
    plugins.import_compat_plugin("pi", source, name="pi-pack")
    monkeypatch.setattr(plugins.shutil, "which", lambda name: "/usr/bin/pi" if name == "pi" else None)

    disabled = plugins.run_pi_plugin_bridge("pi-pack", project=str(tmp_path), dry_run=True)
    assert disabled["ok"] is False
    assert "enabled" in disabled["error"]

    assert plugins.set_plugin_enabled("pi-pack", True)["ok"] is True
    ungranted = plugins.run_pi_plugin_bridge("pi-pack", project=str(tmp_path), dry_run=True)
    assert ungranted["ok"] is False
    assert "external_process" in ungranted["grant_command"]

    assert plugins.set_plugin_grant(
        "pi-pack", scope="project", project=str(tmp_path), permissions=["external_process"]
    )["ok"] is True
    bridged = plugins.run_pi_plugin_bridge("pi-pack", project=str(tmp_path), mode="rpc", dry_run=True)
    assert bridged["ok"] is True
    assert bridged["executed"] is False
    assert bridged["command"][:2] == ["/usr/bin/pi", "--no-extensions"]
    assert "--extension" in bridged["command"]
    assert "--skill" in bridged["command"]
    assert "--prompt-template" in bridged["command"]
    assert bridged["command"][-2:] == ["--mode", "rpc"]

    installed_extension = tmp_path / "installed/pi-pack/compatibility/pi/package/extensions/tools.ts"
    installed_extension.write_text("tampered\n", encoding="utf-8")
    rejected = plugins.run_pi_plugin_bridge("pi-pack", project=str(tmp_path), dry_run=True)
    assert rejected["ok"] is False
    assert rejected["error"] == "Plugin integrity check failed"


def test_pi_bridge_dry_run_does_not_require_pi_installation(tmp_path: Path, monkeypatch) -> None:
    _redirect_plugins(monkeypatch, tmp_path)
    plugins.import_compat_plugin("pi", _pi_package(tmp_path), name="pi-pack")
    assert plugins.set_plugin_enabled("pi-pack", True)["ok"] is True
    assert plugins.set_plugin_grant(
        "pi-pack", scope="user", project=str(tmp_path), permissions=["external_process"]
    )["ok"] is True
    monkeypatch.setattr(plugins.shutil, "which", lambda _name: None)

    result = plugins.run_pi_plugin_bridge("pi-pack", project=str(tmp_path), dry_run=True)

    assert result["ok"] is True
    assert result["command"][0] == "pi"


def test_pi_cli_import_and_bridge_diagnostics(tmp_path: Path, monkeypatch) -> None:
    _redirect_plugins(monkeypatch, tmp_path)
    source = _pi_package(tmp_path)

    imported = runner.invoke(cli_main.app, ["plugin", "import", "pi", str(source), "--name", "cli-pi"])
    bridge = runner.invoke(cli_main.app, ["plugin", "pi", "bridge", "cli-pi", "--dry-run"])

    assert imported.exit_code == 0, imported.output
    assert json.loads(imported.output)["ecosystem"] == "pi"
    assert bridge.exit_code == 1
    assert "must be enabled" in json.loads(bridge.output)["error"]
