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
    assert "MagAgent 0.10.0" in version.output
    assert tutorial.exit_code == 0
    assert "First Project Pass" in tutorial.output


def test_cli_docs_doctor() -> None:
    result = runner.invoke(cli_main.app, ["docs", "doctor"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["missing_topics"] == []
    assert payload["missing_commands"] == []


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
