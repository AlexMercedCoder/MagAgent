from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent import agent as magent_agent
from magent import config as magent_config
from magent import workbench, workbench_store
from magent.cli import main as cli_main
from magent.workbench import WorkbenchStore

runner = CliRunner()


def redirect_config(monkeypatch, root: Path) -> None:
    cfg_dir = root / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", cfg_dir / "users" / "current")
    monkeypatch.setattr(workbench, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(workbench_store, "USERS_DIR", cfg_dir / "users")


def test_cli_version_and_tutorial() -> None:
    version = runner.invoke(cli_main.app, ["--version"])
    tutorial = runner.invoke(cli_main.app, ["tutorial"])

    assert version.exit_code == 0
    assert "MagAgent 0.28.0" in version.output
    assert tutorial.exit_code == 0
    assert "First Project Pass" in tutorial.output


def test_cli_docs_doctor() -> None:
    result = runner.invoke(cli_main.app, ["docs", "doctor"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["missing_topics"] == []
    assert payload["missing_commands"] == []


def test_cli_first_configuration_commands(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("cli-user")
    magent_config.set_current_user("cli-user")

    provider = runner.invoke(
        cli_main.app,
        ["provider", "set", "openai", "--model", "gpt-5", "--api-key-env", "OPENAI_API_KEY"],
    )
    detected = runner.invoke(cli_main.app, ["provider", "detect"])
    roles = runner.invoke(cli_main.app, ["model", "set-role", "review", "anthropic/claude-sonnet-4-5"])
    memory = runner.invoke(
        cli_main.app,
        ["memory", "configure", "--mode", "inbox-first", "--no-semantic", "--write-every", "2"],
    )
    subagents = runner.invoke(
        cli_main.app,
        ["subagent", "configure", "--max", "2", "--parallel", "1", "--model-role", "cheap"],
    )
    gateway = runner.invoke(
        cli_main.app,
        ["gateway", "configure", "telegram", "--bot-token", "secret", "--allowed-user", "123"],
    )
    doctor = runner.invoke(cli_main.app, ["provider", "doctor"])

    assert provider.exit_code == 0
    assert json.loads(provider.output)["provider"] == "openai"
    assert detected.exit_code == 0
    assert any(item["id"] == "openai" for item in json.loads(detected.output)["providers"])
    assert roles.exit_code == 0
    assert json.loads(roles.output)["role"] == "review"
    assert memory.exit_code == 0
    assert json.loads(memory.output)["memory"]["inbox_first"] is True
    assert subagents.exit_code == 0
    assert json.loads(subagents.output)["subagents"]["max_subagents"] == 2
    assert gateway.exit_code == 0
    assert json.loads(gateway.output)["gateway"]["telegram"]["bot_token"] == "***"
    assert doctor.exit_code == 0
    payload = json.loads(doctor.output)
    assert payload["provider"]["provider"] == "openai"
    assert payload["gateways"]["telegram"] is True


def test_cli_guided_ux_commands(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    magent_config.create_user("cli-user")
    magent_config.set_current_user("cli-user")
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    store = WorkbenchStore("cli-user")
    store.append("tasks", {"title": "Remember guided UX", "status": "open"})
    monkeypatch.setattr(cli_main, "_store", lambda: store)

    profiles = runner.invoke(cli_main.app, ["profile", "list"])
    applied = runner.invoke(cli_main.app, ["profile", "apply", "low-cost"])
    lightweight = runner.invoke(cli_main.app, ["profile", "apply", "lightweight"])
    initialized = runner.invoke(cli_main.app, ["project", "init", "--path", str(project)])
    onboarded = runner.invoke(
        cli_main.app,
        ["onboard", "--profile", "coding-local", "--project", str(project), "--yes"],
    )
    suggested = runner.invoke(cli_main.app, ["next", "--project", str(project)])
    doctor = runner.invoke(cli_main.app, ["doctor", "--json"])
    fixed = runner.invoke(cli_main.app, ["doctor", "--fix"])

    assert profiles.exit_code == 0
    assert any(item["name"] == "lightweight" for item in json.loads(profiles.output)["profiles"])
    assert any(item["name"] == "low-cost" for item in json.loads(profiles.output)["profiles"])
    assert applied.exit_code == 0
    assert json.loads(applied.output)["profile"] == "low-cost"
    assert lightweight.exit_code == 0
    assert json.loads(lightweight.output)["profile"] == "lightweight"
    assert initialized.exit_code == 0
    assert (project / ".magent" / "playbook.toml").exists()
    assert onboarded.exit_code == 0
    assert json.loads(onboarded.output)["profile"]["profile"] == "coding-local"
    assert suggested.exit_code == 0
    assert json.loads(suggested.output)["actions"]
    assert doctor.exit_code == 0
    assert "actions" in json.loads(doctor.output)
    assert fixed.exit_code == 0
    assert "after" in json.loads(fixed.output)


def test_cli_provider_ux_and_config_safety_commands(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    from magent import config_safety, providers

    monkeypatch.setattr(config_safety, "CONFIG_DIR", magent_config.CONFIG_DIR)
    monkeypatch.setattr(config_safety, "GLOBAL_CONFIG", magent_config.GLOBAL_CONFIG)
    monkeypatch.setattr(config_safety, "BACKUP_DIR", magent_config.CONFIG_DIR / "backups")
    monkeypatch.setattr(workbench, "USERS_DIR", magent_config.USERS_DIR)
    monkeypatch.setattr(providers, "test_provider", _fake_test_provider)
    magent_config.create_user("cli-user")
    magent_config.set_current_user("cli-user")
    provider = runner.invoke(
        cli_main.app,
        ["provider", "set", "mistral", "--model", "mistral-large-latest", "--api-key-env", "MISTRAL_API_KEY"],
    )
    matrix = runner.invoke(cli_main.app, ["provider", "matrix"])
    explained = runner.invoke(cli_main.app, ["provider", "explain", "mistral"])
    env = runner.invoke(cli_main.app, ["provider", "env"])
    recommended = runner.invoke(cli_main.app, ["provider", "recommend", "--goal", "coding"])
    provider_models = runner.invoke(cli_main.app, ["provider", "models", "mistral"])
    provider_model_recommend = runner.invoke(
        cli_main.app,
        ["provider", "recommend-model", "mistral", "--goal", "cheap"],
    )
    catalog = runner.invoke(cli_main.app, ["provider", "catalog-doctor"])
    test_matrix = runner.invoke(cli_main.app, ["provider", "test-matrix"])
    model_health = runner.invoke(cli_main.app, ["model", "health"])
    readiness = runner.invoke(cli_main.app, ["readiness", "--project", str(tmp_path)])
    permission = runner.invoke(cli_main.app, ["permission", "set", "paranoid"])
    permission_status = runner.invoke(cli_main.app, ["permission", "status"])
    proposed = runner.invoke(cli_main.app, ["config", "propose", "use manual memory and paranoid permissions"])
    proposals = runner.invoke(cli_main.app, ["config", "proposals"])
    backup = runner.invoke(cli_main.app, ["config", "backup"])
    show = runner.invoke(cli_main.app, ["config", "show"])
    diff = runner.invoke(cli_main.app, ["config", "diff"])
    events = runner.invoke(cli_main.app, ["events", "list", "--json"])
    generated = runner.invoke(
        cli_main.app,
        ["docs", "generate-providers", "--out", str(tmp_path / "providers.md")],
    )
    generated_config = runner.invoke(
        cli_main.app,
        ["docs", "generate-config", "--out", str(tmp_path / "config-reference.md")],
    )
    perf = runner.invoke(cli_main.app, ["performance", "doctor", "--json", "--project", str(tmp_path)])
    workbench_stats = runner.invoke(cli_main.app, ["workbench", "stats"])
    workbench_prune = runner.invoke(cli_main.app, ["workbench", "prune", "--dry-run"])
    workbench_compact = runner.invoke(cli_main.app, ["workbench", "compact"])

    assert provider.exit_code == 0
    assert matrix.exit_code == 0
    assert "mistral" in matrix.output
    assert explained.exit_code == 0
    assert json.loads(explained.output)["provider"] == "mistral"
    assert env.exit_code == 0
    assert any(item["provider"] == "mistral" for item in json.loads(env.output)["providers"])
    assert recommended.exit_code == 0
    assert any(item["id"] == "mistral" for item in json.loads(recommended.output)["recommendations"])
    assert provider_models.exit_code == 0
    assert "mistral-large-latest" in json.loads(provider_models.output)["models"]
    assert provider_model_recommend.exit_code == 0
    assert json.loads(provider_model_recommend.output)["ok"] is True
    assert catalog.exit_code == 0
    assert json.loads(catalog.output)["ok"] is True
    assert test_matrix.exit_code == 0
    assert any(item["provider"] == "mistral" for item in json.loads(test_matrix.output)["providers"])
    assert model_health.exit_code == 0
    assert readiness.exit_code == 0
    assert permission.exit_code == 0
    assert json.loads(permission.output)["mode"] == "paranoid"
    assert permission_status.exit_code == 0
    assert json.loads(permission_status.output)["mode"] == "paranoid"
    assert proposed.exit_code == 0
    assert json.loads(proposed.output)["proposal"]["id"]
    assert proposals.exit_code == 0
    assert json.loads(proposals.output)["proposals"]
    assert backup.exit_code == 0
    assert json.loads(backup.output)["backup_id"]
    assert show.exit_code == 0
    assert json.loads(show.output)["files"]["global"]["exists"] is True
    assert diff.exit_code == 0
    assert events.exit_code == 0
    assert json.loads(events.output)["events"]
    assert generated.exit_code == 0
    assert (tmp_path / "providers.md").exists()
    assert generated_config.exit_code == 0
    assert (tmp_path / "config-reference.md").exists()
    assert perf.exit_code == 0
    assert json.loads(perf.output)["repo"]["files_seen"] >= 0
    assert workbench_stats.exit_code == 0
    assert json.loads(workbench_stats.output)["ok"] is True
    assert workbench_prune.exit_code == 0
    assert json.loads(workbench_prune.output)["dry_run"] is True
    assert workbench_compact.exit_code == 0
    assert json.loads(workbench_compact.output)["ok"] is True


def test_cli_provider_tool_smoke_uses_agent_session(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("cli-user")
    magent_config.set_current_user("cli-user")

    class FakeSession:
        def __init__(self, **kwargs):
            self.cwd = kwargs["cwd"]
            self.scratchpad = {"files_touched": [str(Path(self.cwd) / "smoke.txt")]}

        async def chat(self, prompt: str) -> str:
            Path(self.cwd, "smoke.txt").write_text("OK", encoding="utf-8")
            return "done"

        async def end_session(self) -> None:
            return None

    monkeypatch.setattr(magent_agent, "AgentSession", FakeSession)
    import magent.provider_smoke

    monkeypatch.setattr(magent.provider_smoke, "AgentSession", FakeSession)
    result = runner.invoke(
        cli_main.app,
        ["provider", "tool-smoke", "openai", "--project", str(tmp_path / "smoke")],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["artifact_ok"] is True


async def _fake_test_provider(provider) -> bool:
    return True


def test_cli_ui_starts_local_operations_dashboard(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("cli-test")
    monkeypatch.setattr(cli_main, "_store", lambda: store)
    monkeypatch.setattr(cli_main, "_require_user", lambda: "cli-test")

    import magent.ui

    monkeypatch.setattr(
        magent.ui,
        "serve_ui",
        lambda store, project, username, port, open_browser: {
            "ok": True,
            "url": f"http://127.0.0.1:{port}/",
            "project": project,
            "username": username,
        },
    )
    monkeypatch.setattr(
        cli_main.signal,
        "pause",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    result = runner.invoke(cli_main.app, ["ui", "--project", str(project), "--port", "9999"])

    assert result.exit_code == 0
    assert "http://127.0.0.1:9999/" in result.output
    assert "cli-test" in result.output


def test_cli_context_map_and_memory_promote(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("cli-test")
    store.append("tasks", {"title": "Remember the release checklist", "status": "open"})
    monkeypatch.setattr(cli_main, "_store", lambda: store)

    class FakeMemory:
        available = True

        def __init__(self):
            self.written = []

        def stats(self):
            return {"nodes": 0}

        def recall(self, query):
            return f"Recall {query}"

        def write_memories(self, extracted, project_slug=None):
            self.written.extend(extracted)
            return len(extracted)

    memory = FakeMemory()
    monkeypatch.setattr(cli_main, "_get_memory_manager", lambda: (memory, "cli-test"))

    mapped = runner.invoke(cli_main.app, ["context", "map", "--project", str(project), "--query", "release"])
    listed = runner.invoke(cli_main.app, ["memory", "promote", "--project", str(project)])
    promoted = runner.invoke(cli_main.app, ["memory", "promote", "task", "task_0001", "--project", str(project)])

    assert mapped.exit_code == 0
    assert json.loads(mapped.output)["memory"]["recall"] == "Recall release"
    assert listed.exit_code == 0
    assert json.loads(listed.output)["candidates"]
    assert promoted.exit_code == 0
    assert json.loads(promoted.output)["written"] == 1


def test_cli_recipes_playbook_tools_and_memory_inbox(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    (project / ".magent").mkdir(parents=True)
    (project / ".magent" / "playbook.toml").write_text(
        "[commands]\ntest = ['pytest -q']\nrelease = 'python -m build'\n"
        "[release]\nchecklist = ['Update docs']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("cli-test")
    store.append("tasks", {"title": "Remember inbox task", "status": "open"})
    monkeypatch.setattr(cli_main, "_store", lambda: store)

    class FakeMemory:
        available = True

        def __init__(self):
            self.written = []

        def write_memories(self, extracted, project_slug=None):
            self.written.extend(extracted)
            return len(extracted)

    memory = FakeMemory()
    monkeypatch.setattr(cli_main, "_get_memory_manager", lambda: (memory, "cli-test"))

    playbook = runner.invoke(cli_main.app, ["project", "playbook", "--path", str(project)])
    recipes = runner.invoke(cli_main.app, ["recipe", "list", "--project", str(project)])
    saved = runner.invoke(
        cli_main.app,
        [
            "recipe",
            "save",
            "daily-check",
            "--description",
            "Daily checks",
            "--step",
            "Run tests",
            "--command",
            "pytest -q",
        ],
    )
    run = runner.invoke(cli_main.app, ["recipe", "run", "daily-check", "--project", str(project)])
    tools = runner.invoke(cli_main.app, ["tools", "disable", "web"])
    explained = runner.invoke(cli_main.app, ["tools", "explain", "web"])
    inbox = runner.invoke(cli_main.app, ["memory", "inbox", "--project", str(project)])
    accepted = runner.invoke(
        cli_main.app,
        ["memory", "inbox", "accept", "promoted_task_task_0001_remember_inbox_task", "--project", str(project)],
    )

    assert playbook.exit_code == 0
    assert json.loads(playbook.output)["commands"]["test"] == ["pytest -q"]
    assert recipes.exit_code == 0
    assert "project-playbook" in recipes.output
    assert saved.exit_code == 0
    assert json.loads(saved.output)["name"] == "daily-check"
    assert run.exit_code == 0
    assert json.loads(run.output)["plan"]["recipe"]["name"] == "daily-check"
    assert tools.exit_code == 0
    assert json.loads(tools.output)["enabled"] is False
    assert explained.exit_code == 0
    assert json.loads(explained.output)["enabled"] is False
    assert inbox.exit_code == 0
    assert json.loads(inbox.output)["candidates"]
    assert accepted.exit_code == 0
    assert json.loads(accepted.output)["written"] == 1


def test_cli_code_and_test_commands(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "src" / "orders.py").write_text(
        "def create_order():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_orders.py").write_text(
        "from src.orders import create_order\n\n"
        "def test_create_order():\n    assert create_order()['ok']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("cli-test")
    monkeypatch.setattr(cli_main, "_store", lambda: store)

    indexed = runner.invoke(cli_main.app, ["code", "index", "--project", str(project)])
    symbols = runner.invoke(cli_main.app, ["code", "symbols", "create_order", "--project", str(project)])
    related_code = runner.invoke(
        cli_main.app,
        ["code", "related", str(project / "src" / "orders.py"), "--project", str(project)],
    )
    related_tests = runner.invoke(
        cli_main.app,
        ["test", "related", str(project / "src" / "orders.py"), "--project", str(project)],
    )
    explained = runner.invoke(
        cli_main.app,
        ["test", "explain", str(project / "src" / "orders.py"), "--project", str(project)],
    )

    assert indexed.exit_code == 0
    assert json.loads(indexed.output)["symbols"] == 2
    assert symbols.exit_code == 0
    assert "create_order" in symbols.output
    assert related_code.exit_code == 0
    assert json.loads(related_code.output)["tests"] == ["tests/test_orders.py"]
    assert related_tests.exit_code == 0
    assert "tests/test_orders.py" in related_tests.output
    assert explained.exit_code == 0
    assert json.loads(explained.output)["count"] == 1


def test_cli_project_patch_workspace_and_release_commands(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".magent").mkdir()
    (project / ".magent" / "config.toml").write_text(
        "[commands]\ntest = 'pytest -q'\nlint = 'ruff check src tests'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("cli-test")
    monkeypatch.setattr(cli_main, "_store", lambda: store)
    monkeypatch.setattr(
        workbench,
        "release_check",
        lambda store, project: {"ok": True, "checks": [{"name": "tests", "ok": True}]},
    )
    monkeypatch.setattr(
        workbench,
        "release_notes",
        lambda project, since="HEAD~5": {"ok": True, "markdown": "# Notes"},
    )
    patch = store.append(
        "patches",
        {
            "name": "demo",
            "path": str(project / "demo.patch"),
            "bytes": 20,
            "root": str(project),
        },
    )
    (project / "demo.patch").write_text("diff --git a/a b/a\n+++ b/a\n+new\n", encoding="utf-8")

    roles = runner.invoke(cli_main.app, ["project", "roles", "--path", str(project)])
    doctor = runner.invoke(cli_main.app, ["project", "doctor", "--path", str(project)])
    preview = runner.invoke(cli_main.app, ["patch", "preview", patch["id"]])
    explain = runner.invoke(cli_main.app, ["patch", "explain", patch["id"]])
    workspace_status = runner.invoke(cli_main.app, ["workspace", "status", "--project", str(project)])
    release_check = runner.invoke(cli_main.app, ["release", "check", "--project", str(project)])
    release_notes = runner.invoke(cli_main.app, ["release", "notes", "--project", str(project)])

    assert roles.exit_code == 0
    assert json.loads(roles.output)["test"] == "pytest -q"
    assert doctor.exit_code == 0
    assert "missing" in json.loads(doctor.output)
    assert preview.exit_code == 0
    assert json.loads(preview.output)["stats"]["added"] == 1
    assert explain.exit_code == 0
    assert "changes" in json.loads(explain.output)["summary"]
    assert workspace_status.exit_code == 0
    assert json.loads(workspace_status.output)["patches"] == 1
    assert release_check.exit_code == 0
    assert json.loads(release_check.output)["ok"] is True
    assert release_notes.exit_code == 0
    assert json.loads(release_notes.output)["markdown"] == "# Notes"


def test_cli_memory_quality(monkeypatch) -> None:
    class FakeManager:
        def quality_report(self):
            return {"ok": True, "nodes": 1, "duplicates": [], "suppressed": []}

        def merge_preview(self, target_id, source_id):
            return {"ok": True, "target": target_id, "source": source_id}

        def unsuppress_node(self, node_id):
            return {"ok": True, "id": node_id}

    monkeypatch.setattr(cli_main, "_get_memory_manager", lambda: (FakeManager(), object()))

    result = runner.invoke(cli_main.app, ["memory", "quality"])
    preview = runner.invoke(cli_main.app, ["memory", "merge", "a", "b", "--preview"])
    unsuppress = runner.invoke(cli_main.app, ["memory", "unsuppress", "a"])

    assert result.exit_code == 0
    assert json.loads(result.output)["nodes"] == 1
    assert preview.exit_code == 0
    assert json.loads(preview.output)["source"] == "b"
    assert unsuppress.exit_code == 0
    assert json.loads(unsuppress.output)["id"] == "a"
