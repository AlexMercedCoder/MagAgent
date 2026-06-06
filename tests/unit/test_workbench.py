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


def test_save_and_apply_plan(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    item = workbench.save_plan(store, project, "Ship a feature")
    result = workbench.apply_plan(store, item["id"])

    assert result["ok"] is True
    assert result["plan"]["status"] == "applied"


def test_apply_saved_patch_reports_missing_patch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")

    result = workbench.apply_saved_patch(store, "patch_404")

    assert result["ok"] is False


def test_checkpoint_restore_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    target = tmp_path / "project" / "app.py"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")

    checkpoint = workbench.create_checkpoint("alice", target.parent, target, "edit_file")
    target.write_text("new", encoding="utf-8")
    store = workbench.WorkbenchStore("alice")
    result = workbench.restore_checkpoint(store, checkpoint["id"])

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "old"


def test_checkpoint_restore_created_file_removes_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    target = tmp_path / "project" / "created.py"
    target.parent.mkdir()

    checkpoint = workbench.create_checkpoint("alice", target.parent, target, "write_file")
    target.write_text("created", encoding="utf-8")
    store = workbench.WorkbenchStore("alice")
    result = workbench.restore_checkpoint(store, checkpoint["id"])

    assert result["ok"] is True
    assert not target.exists()


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
