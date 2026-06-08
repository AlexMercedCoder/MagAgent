from __future__ import annotations

from pathlib import Path

from magent import workbench
from magent.context import (
    context_map,
    promote_all_candidates,
    promote_candidate,
    promotion_candidates,
)
from magent.workbench import WorkbenchStore, task_add


class FakeMemory:
    available = True

    def __init__(self) -> None:
        self.written: list[dict] = []

    def write_memories(self, extracted, project_slug=None):
        self.written.extend(extracted)
        self.project_slug = project_slug
        return len(extracted)

    def stats(self):
        return {"nodes": len(self.written)}

    def recall(self, query):
        return f"Recall for {query}"


def test_promotion_candidates_include_project_tasks_plans_and_failures(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".magent").mkdir()
    (project / ".magent" / "config.toml").write_text(
        "[commands]\ntest = 'pytest -q'\nlint = 'ruff check src tests'\n",
        encoding="utf-8",
    )
    store = WorkbenchStore("context-test")
    task_add(store, "Remember release checklist", project=str(project), priority="high")
    store.append("plans", {"goal": "Ship memory promotion", "status": "pending", "project": str(project)})
    store.append(
        "command_history",
        {
            "root": str(project.resolve()),
            "command": "pytest -q",
            "ok": False,
            "stderr": "failed assertion",
        },
    )

    candidates = promotion_candidates(store, project)
    sources = {item["source"] for item in candidates}

    assert {"project", "task", "plan", "command"} <= sources
    assert any("PromotedFrom:" in item["body"] for item in candidates)


def test_promotion_candidates_skip_trivial_draft_plans(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    project = tmp_path / "project"
    project.mkdir()
    store = WorkbenchStore("context-test")
    store.append(
        "plans",
        {
            "id": "plan_math",
            "goal": "What is 2 + 2",
            "status": "draft",
            "project": "project",
            "plan_markdown": "# Plan\n\n- generic",
        },
    )
    store.append(
        "plans",
        {
            "id": "plan_real",
            "goal": "Improve release workflow reliability",
            "status": "pending",
            "project": "project",
            "plan_markdown": "# Plan\n\n- useful",
        },
    )

    candidates = promotion_candidates(store, project)

    assert not any(item["source_id"] == "plan_math" for item in candidates)
    assert any(item["source_id"] == "plan_real" for item in candidates)


def test_promote_candidate_writes_one_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("context-test")
    task = task_add(store, "Keep docs current")
    memory = FakeMemory()

    result = promote_candidate(store, memory, "task", task["id"], project=tmp_path)

    assert result["ok"] is True
    assert result["written"] == 1
    assert memory.written[0]["source"] == "task"
    assert memory.project_slug == tmp_path.name


def test_promote_all_candidates_writes_everything(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("context-test")
    task_add(store, "Document context map")
    task_add(store, "Document memory promote")
    memory = FakeMemory()

    result = promote_all_candidates(store, memory, project=tmp_path)

    assert result["ok"] is True
    assert result["written"] == len(result["candidates"])
    assert len(memory.written) == result["written"]


def test_context_map_combines_memory_and_workbench(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("context-test")
    task_add(store, "Promote important facts")
    memory = FakeMemory()

    result = context_map(store, tmp_path, memory_manager=memory, query="release")

    assert result["ok"] is True
    assert result["memory"]["available"] is True
    assert result["memory"]["recall"] == "Recall for release"
    assert result["active_workbench"]["tasks"]
    assert result["promotion_candidates"]
