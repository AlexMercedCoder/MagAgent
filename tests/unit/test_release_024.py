from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from magent import config as magent_config
from magent import plugins, workbench
from magent.agent_defs import create_agent, list_agents, resolve_invocation
from magent.cli import main as cli_main
from magent.daemon import enqueue_task, list_queue, run_once
from magent.hooks import init_hooks, load_hooks, run_hooks
from magent.lsp import lsp_definition, lsp_diagnostics, lsp_references, lsp_status, lsp_symbols
from magent.plugins import install_plugin, list_plugins, set_plugin_enabled

runner = CliRunner()


def redirect_config(monkeypatch, root: Path) -> None:
    cfg_dir = root / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", cfg_dir / "users" / "current")


def test_agent_definition_system_loads_project_agents(tmp_path: Path) -> None:
    result = create_agent(
        tmp_path,
        "reviewer",
        description="Review things",
        prompt="Review code carefully.",
    )
    agents = list_agents(tmp_path)
    invocation = resolve_invocation("@reviewer inspect this diff", tmp_path)

    assert result["ok"] is True
    assert any(item["name"] == "reviewer" for item in agents["agents"])
    assert invocation["ok"] is True
    assert "Review code carefully" in invocation["message"]


def test_hooks_run_project_commands(tmp_path: Path) -> None:
    init = init_hooks(tmp_path)
    hooks_path = Path(init["path"])
    hooks_path.write_text(
        "[hooks]\npre_tool = 'python -c \"import os; print(os.environ[\\\"MAGENT_HOOK_EVENT\\\"])\"'\n",
        encoding="utf-8",
    )

    hooks = load_hooks(tmp_path)
    results = run_hooks(tmp_path, "pre_tool", {"tool": "read_file"})

    assert hooks["pre_tool"]
    assert results[0]["ok"] is True
    assert "pre_tool" in results[0]["stdout"]


def test_lsp_fallback_intelligence(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def hello():\n    return 'hi'\n\nhello()\n", encoding="utf-8")

    assert lsp_status()["ok"] is True
    assert lsp_diagnostics(tmp_path)["ok"] is True
    assert lsp_symbols(tmp_path, "hello")["symbols"][0]["name"] == "hello"
    assert lsp_definition(tmp_path, "hello")["definitions"]
    assert lsp_references(tmp_path, "hello")["references"]


def test_daemon_queue_runs_shell_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = workbench.WorkbenchStore("alice")
    enqueue_task(store, "shell", {"command": "python --version"}, project=tmp_path)

    listed = list_queue(store)
    ran = run_once(store)

    assert listed["tasks"][0]["kind"] == "shell"
    assert ran["ran"] == 1
    assert ran["ok"] is True


def test_plugin_install_enable_and_agent_discovery(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setattr(plugins, "PLUGIN_DIR", magent_config.CONFIG_DIR / "plugins")
    monkeypatch.setattr(plugins, "PLUGIN_STATE", magent_config.CONFIG_DIR / "plugins.toml")
    source = tmp_path / "pack"
    (source / "agents").mkdir(parents=True)
    (source / "magent-plugin.toml").write_text("[plugin]\nname='demo'\nversion='1.0.0'\n", encoding="utf-8")
    (source / "agents" / "audit.md").write_text("---\ndescription: Audit\n---\nAudit things.\n", encoding="utf-8")

    installed = install_plugin(source)
    enabled = set_plugin_enabled("demo", True)
    listed = list_plugins()
    agents = list_agents(tmp_path)

    assert installed["ok"] is True
    assert enabled["enabled"] is True
    assert listed["plugins"][0]["name"] == "demo"
    assert any(item["name"] == "audit" for item in agents["agents"])


def test_cli_release_024_commands(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setattr(workbench, "USERS_DIR", magent_config.USERS_DIR)
    magent_config.create_user("cli-user")
    magent_config.set_current_user("cli-user")
    (tmp_path / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    created = runner.invoke(cli_main.app, ["agent", "create", "reviewer", "--project", str(tmp_path), "--prompt", "Review."])
    agents = runner.invoke(cli_main.app, ["agent", "list", "--project", str(tmp_path)])
    hooks = runner.invoke(cli_main.app, ["hook", "init", "--project", str(tmp_path)])
    lsp = runner.invoke(cli_main.app, ["lsp", "symbols", "--project", str(tmp_path), "--query", "hello"])
    queued = runner.invoke(cli_main.app, ["daemon", "enqueue", "shell", "python --version", "--project", str(tmp_path)])
    queue = runner.invoke(cli_main.app, ["daemon", "list"])
    plugins_list = runner.invoke(cli_main.app, ["plugin", "list"])

    assert created.exit_code == 0
    assert agents.exit_code == 0
    assert hooks.exit_code == 0
    assert lsp.exit_code == 0
    assert queued.exit_code == 0
    assert queue.exit_code == 0
    assert plugins_list.exit_code == 0
