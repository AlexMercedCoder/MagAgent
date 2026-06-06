from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent import workbench
from magent.cli import main as cli_main
from magent.workbench import WorkbenchStore

runner = CliRunner()


def test_cli_version_and_tutorial() -> None:
    version = runner.invoke(cli_main.app, ["--version"])
    tutorial = runner.invoke(cli_main.app, ["tutorial"])

    assert version.exit_code == 0
    assert "MagAgent 0.14.0" in version.output
    assert tutorial.exit_code == 0
    assert "First Project Pass" in tutorial.output


def test_cli_docs_doctor() -> None:
    result = runner.invoke(cli_main.app, ["docs", "doctor"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["missing_topics"] == []
    assert payload["missing_commands"] == []


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
