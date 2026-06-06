from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from magent import config as magent_config
from magent import plugins
from magent.cli import main as cli_main
from magent.config import load_global_config
from magent.plugins import (
    apply_plugin_mcp,
    import_compat_plugin,
    import_mcp_plugin,
    list_plugins,
    normalize_plugin_metadata,
    set_plugin_enabled,
)

runner = CliRunner()


def redirect_config(monkeypatch, root: Path) -> None:
    cfg_dir = root / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", cfg_dir / "users" / "current")
    monkeypatch.setattr(plugins, "PLUGIN_DIR", cfg_dir / "plugins")
    monkeypatch.setattr(plugins, "PLUGIN_STATE", cfg_dir / "plugins.toml")


def test_mcp_plugin_import_enable_and_config_merge(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    source = tmp_path / "mcp.toml"
    source.write_text(
        "[mcp.servers.files]\ncommand = 'npx'\nargs = ['-y', '@modelcontextprotocol/server-filesystem', '.']\n",
        encoding="utf-8",
    )

    imported = import_mcp_plugin(source, name="filesystem")
    set_plugin_enabled("filesystem", True)
    cfg = load_global_config()

    assert imported["ok"] is True
    assert imported["servers"] == ["files"]
    assert cfg["mcp"]["servers"]["files"]["command"] == "npx"
    assert cfg["mcp"]["servers"]["files"]["source_plugin"] == "filesystem"


def test_mcp_plugin_apply_writes_global_config(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    source = tmp_path / "pack"
    source.mkdir()
    (source / "mcp.json").write_text(
        '{"mcpServers":{"github":{"command":"npx","args":["-y","server"]}}}',
        encoding="utf-8",
    )

    imported = import_mcp_plugin(source, name="github-mcp")
    applied = apply_plugin_mcp("github-mcp")

    assert imported["ok"] is True
    assert applied["added"] == ["github"]
    assert "github" in magent_config.GLOBAL_CONFIG.read_text(encoding="utf-8")


def test_manifest_adapters_detect_foreign_metadata(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    source = tmp_path / "foreign"
    source.mkdir()
    (source / "package.json").write_text(
        '{"name":"@scope/demo","version":"1.2.3","description":"Demo","repository":{"url":"https://example.com/demo"}}',
        encoding="utf-8",
    )
    (source / "AGENTS.md").write_text("Use careful review.", encoding="utf-8")

    metadata = normalize_plugin_metadata(source)

    assert metadata["name"] == "demo"
    assert "node-package" in metadata["compatibility"]
    assert "agents-md" in metadata["compatibility"]
    assert "agents" in metadata["capabilities"]
    assert metadata["source_url"] == "https://example.com/demo"


def test_importers_convert_known_ecosystem_shapes(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    opencode = tmp_path / "opencode"
    (opencode / "agents").mkdir(parents=True)
    (opencode / "commands").mkdir()
    (opencode / "agents" / "review.md").write_text("Review prompt", encoding="utf-8")
    (opencode / "commands" / "release.md").write_text("Release recipe", encoding="utf-8")

    claude = tmp_path / "claude"
    claude.mkdir()
    (claude / "CLAUDE.md").write_text("Claude project instructions", encoding="utf-8")

    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n# Demo", encoding="utf-8")

    imported_open = import_compat_plugin("opencode", opencode, name="open-pack")
    imported_claude = import_compat_plugin("claude", claude, name="claude-pack")
    imported_skill = import_compat_plugin("codex-skill", skill, name="skill-pack")
    listed = list_plugins()

    assert imported_open["converted"]["agents"]
    assert imported_open["converted"]["recipes"]
    assert imported_claude["converted"]["agents"]
    assert imported_skill["converted"]["skills"]
    assert {item["name"] for item in listed["plugins"]} >= {"open-pack", "claude-pack", "skill-pack"}


def test_cli_plugin_compatibility_commands(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    mcp_file = tmp_path / "mcp.toml"
    mcp_file.write_text("[mcp.servers.demo]\ncommand = 'python'\nargs = ['--version']\n", encoding="utf-8")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: cli-skill\n---\n# CLI Skill", encoding="utf-8")

    mcp_import = runner.invoke(cli_main.app, ["plugin", "mcp", "import", str(mcp_file), "--name", "cli-mcp"])
    metadata = runner.invoke(cli_main.app, ["plugin", "metadata", str(skill)])
    skill_import = runner.invoke(cli_main.app, ["plugin", "import", "codex-skill", str(skill), "--name", "cli-skill"])

    assert mcp_import.exit_code == 0
    assert metadata.exit_code == 0
    assert skill_import.exit_code == 0
