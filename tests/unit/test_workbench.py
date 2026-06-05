"""Tests for durable workbench primitives."""

from pathlib import Path

from magent import workbench


def test_task_artifact_and_knowledge_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")

    task = workbench.task_add(store, "Fix auth tests", project="api", priority="high")
    artifact = workbench.artifact_add(store, "report.md", kind="doc")
    note = workbench.remember(store, "User prefers pytest and small patches", ["pytest"])

    assert task["id"] == "task_0001"
    assert artifact["kind"] == "doc"
    assert note in workbench.recall(store, "pytest")
    assert workbench.task_list(store, status="open")[0]["title"] == "Fix auth tests"


def test_project_profile_and_plan(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    profile = workbench.project_profile(tmp_path)
    plan = workbench.build_plan(tmp_path, "Add a feature")

    assert "pyproject.toml" in profile["detected_files"]
    assert "pytest -q" in profile["commands"]
    assert "Add a feature" in plan


def test_repo_graph_and_data_inspect(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import json\nfrom pathlib import Path\n", encoding="utf-8")
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("name,age\nAda,37\n", encoding="utf-8")

    graph = workbench.repo_graph(tmp_path)
    data = workbench.inspect_data(str(csv_path))

    assert graph["files"] == 1
    assert "json" in graph["python_imports"]["app.py"]
    assert data["kind"] == "csv"
    assert data["rows"] == 1


def test_notes_ingest_creates_tasks_and_decisions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")

    result = workbench.ingest_notes(
        store,
        "- TODO follow up on CI\n- Decision: use SQLite for local state\n",
    )

    assert len(result["tasks"]) == 1
    assert len(result["decisions"]) == 1
