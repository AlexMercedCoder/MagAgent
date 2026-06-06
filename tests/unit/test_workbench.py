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


def test_project_command_discovery_reads_local_config_and_manifests(tmp_path: Path) -> None:
    (tmp_path / ".magent").mkdir()
    (tmp_path / ".magent" / "config.toml").write_text(
        "[commands]\ntest = 'pytest tests/unit'\n", encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest","lint":"eslint .","build":"vite build"}}',
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text("check:\n\ttrue\n", encoding="utf-8")

    commands = workbench.infer_project_commands(tmp_path)
    profile = workbench.project_profile(tmp_path)

    assert "pytest tests/unit" in commands
    assert "npm test" in commands
    assert "npm run lint" in commands
    assert "make check" in commands
    assert profile["config"]["commands"]["test"] == "pytest tests/unit"


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


def test_plan_show_and_discard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")
    item = workbench.save_plan(store, tmp_path, "Do it")

    assert workbench.show_plan(store, item["id"]) is not None
    result = workbench.discard_plan(store, item["id"])

    assert result["ok"] is True
    assert result["plan"]["status"] == "discarded"


def test_save_execution_plan_with_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")

    item = workbench.save_execution_plan(
        store,
        tmp_path,
        "Run checks",
        commands=["python --version"],
        include_diff=False,
    )

    assert item["mode"] == "execution"
    assert item["operations"][0]["type"] == "shell"
    assert "python --version" in item["preview"]


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


def test_checkpoint_diff(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    target = tmp_path / "project" / "app.py"
    target.parent.mkdir()
    target.write_text("old\n", encoding="utf-8")
    checkpoint = workbench.create_checkpoint("alice", target.parent, target, "edit_file")
    target.write_text("new\n", encoding="utf-8")
    store = workbench.WorkbenchStore("alice")

    result = workbench.checkpoint_diff(store, checkpoint["id"])

    assert result["ok"] is True
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]


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


def test_checkpoint_session_restore(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    target = tmp_path / "project" / "session.py"
    target.parent.mkdir()
    target.write_text("before", encoding="utf-8")
    checkpoint = workbench.create_checkpoint(
        "alice", target.parent, target, "edit_file", session_id="sess1"
    )
    target.write_text("after", encoding="utf-8")
    store = workbench.WorkbenchStore("alice")

    sessions = workbench.checkpoint_sessions(store)
    diff = workbench.checkpoint_session_diff(store, "sess1")
    restored = workbench.checkpoint_session_restore(store, "sess1")

    assert sessions[0]["session_id"] == "sess1"
    assert checkpoint["id"] in [item["checkpoint"] for item in restored["results"]]
    assert "-before" in diff["diff"]
    assert target.read_text(encoding="utf-8") == "before"


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


def test_code_index_symbols_and_related_tests(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "billing.py").write_text(
        'class Invoice:\n    """Invoice record."""\n\n'
        "def total(items):\n    return sum(items)\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_billing.py").write_text(
        "from src.billing import total\n\n"
        "def test_total():\n    assert total([1, 2]) == 3\n",
        encoding="utf-8",
    )

    index = workbench.code_index(tmp_path)

    assert index["root"] == str(tmp_path.resolve())
    assert "src/billing.py" in index["test_map"]
    assert index["test_map"]["src/billing.py"] == ["tests/test_billing.py"]
    assert any(symbol["name"] == "Invoice" for symbol in index["symbols"])
    assert workbench.related_tests(tmp_path, "src/billing.py") == ["tests/test_billing.py"]


def test_code_index_persistence_symbol_search_and_related_code(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
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
    store = workbench.WorkbenchStore("alice")

    saved = workbench.save_code_index(store, project)
    matches = workbench.search_symbols(store, "create_order", project)
    related = workbench.related_code(store, project, "src/orders.py")

    assert saved["symbols"]
    assert any(match["path"] == "src/orders.py" for match in matches)
    assert related["tests"] == ["tests/test_orders.py"]
    assert "tests/test_orders.py" in related["related"]


def test_review_summary_has_categories(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=tmp_path, capture_output=True, text=True)
    (tmp_path / "src" / "app.py").write_text("print('debug')\n", encoding="utf-8")

    summary = workbench.review_summary(tmp_path)

    assert summary["findings"]
    assert "debugging" in summary["categories"] or "tests" in summary["categories"]


def test_saved_review_and_command_learning_and_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")
    artifact_path = tmp_path / "report.txt"
    artifact_path.write_text("hello", encoding="utf-8")

    review = workbench.save_review(store, tmp_path)
    history = workbench.record_command_result(store, tmp_path, "pytest -q", True)
    promoted = workbench.promote_command(store, tmp_path, "pytest -q")
    artifact = workbench.artifact_add(store, str(artifact_path))
    checksum = workbench.artifact_checksum(store, artifact["id"])

    assert workbench.review_show(store, review["id"]) is not None
    assert workbench.command_history(store, tmp_path)[0]["id"] == history["id"]
    assert "pytest -q" in promoted["commands"]
    assert checksum["ok"] is True
    assert workbench.artifact_show(store, artifact["id"]) is not None


def test_ci_repair_plan_guess(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    plan = workbench.ci_repair_plan(tmp_path, {"failed_log": "pytest failed"})

    assert plan["reproduce"] == "pytest -q"
    assert plan["steps"]


def test_notes_ingest_creates_tasks_and_decisions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path)
    store = workbench.WorkbenchStore("alice")

    result = workbench.ingest_notes(
        store,
        "- TODO follow up on CI\n- Decision: use SQLite for local state\n",
    )

    assert len(result["tasks"]) == 1
    assert len(result["decisions"]) == 1
