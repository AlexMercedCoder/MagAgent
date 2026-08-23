from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

import magent.web_graphs as web_graphs
from magent.config import DEFAULT_GLOBAL_CONFIG, Config
from magent.web_graphs import (
    GraphRunManager,
    blank_graph_document,
    confined_graph_path,
    confined_graph_target,
    generate_web_graph,
    graph_catalog,
    preview_web_graph,
    save_web_graph,
    web_task_node,
)
from magent.workbench_store import WorkbenchStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def graph_project(tmp_path: Path) -> tuple[Path, Path, WorkbenchStore]:
    project = tmp_path / "project"
    project.mkdir()
    graph = project / "release.agraph.yaml"
    shutil.copy(ROOT / "docs/examples/agraph/minimal.agraph.yaml", graph)
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "graph-web-test"
    store.root = tmp_path / "workbench"
    store.root.mkdir()
    store.warnings = []
    return project, graph, store


def test_graph_catalog_and_path_confinement(graph_project, tmp_path: Path) -> None:
    project, graph, store = graph_project
    catalog = graph_catalog(store, project)

    assert catalog["graphs"][0]["path"] == str(graph)
    assert confined_graph_path(project, "release.agraph.yaml") == graph
    outside = tmp_path / "outside.agraph.yaml"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="inside"):
        confined_graph_path(project, str(outside))
    assert confined_graph_target(project, "new.agraph.yaml") == project / "new.agraph.yaml"
    with pytest.raises(ValueError, match="must use"):
        confined_graph_target(project, "new.yaml")


def test_blank_graph_cards_validate_and_save(graph_project, monkeypatch) -> None:
    project, _graph, _store = graph_project
    config = Config(DEFAULT_GLOBAL_CONFIG)
    monkeypatch.setattr(web_graphs, "load_config", lambda _username: config)
    document = blank_graph_document("Prepare a release")
    document["nodes"]["prepare"] = web_task_node()
    document["nodes"]["prepare"]["title"] = "Prepare release"
    document["entrypoints"] = ["prepare"]
    document["outputs"] = {
        "summary": {
            "type": "markdown",
            "description": "Release preparation summary.",
            "from": "nodes.prepare.outputs.summary",
        }
    }

    preview = preview_web_graph(document, project=project, username="alex")
    saved = save_web_graph(
        document,
        "authored.agraph.yaml",
        project=project,
        username="alex",
    )

    assert preview["ok"] is True
    assert preview["plan"]["nodes"][0]["id"] == "prepare"
    assert saved["ok"] is True
    assert (project / "authored.agraph.yaml").is_file()


def test_invalid_web_graph_returns_a_human_validation_error(graph_project, monkeypatch) -> None:
    project, _graph, _store = graph_project
    monkeypatch.setattr(
        web_graphs,
        "load_config",
        lambda _username: Config(DEFAULT_GLOBAL_CONFIG),
    )

    result = preview_web_graph(blank_graph_document(), project=project, username="alex")

    assert result["ok"] is False
    assert result["error"]
    assert result["error"] != "Graph validation failed"


@pytest.mark.asyncio
async def test_ai_graph_generation_uses_review_only_model_contract(graph_project, monkeypatch) -> None:
    project, _graph, _store = graph_project
    expected = {"ok": True, "document": {"id": "generated"}}
    captured = {}

    async def fake_model(goal, **kwargs):
        captured.update(goal=goal, **kwargs)
        return expected

    monkeypatch.setattr(web_graphs, "model_graph_draft", fake_model)
    monkeypatch.setattr(web_graphs, "load_config", lambda _username: Config(DEFAULT_GLOBAL_CONFIG))

    result = await generate_web_graph("Build the onboarding flow", project=project, username="alex")

    assert result == expected
    assert captured["goal"] == "Build the onboarding flow"
    assert "dependency graph" in captured["instruction"]


def test_graph_preview_exposes_dependencies_and_profiles(graph_project, monkeypatch) -> None:
    project, graph, store = graph_project
    monkeypatch.setattr(web_graphs, "load_config", lambda _username: Config(DEFAULT_GLOBAL_CONFIG))

    result = GraphRunManager(store, "alex", project).preview(str(graph))

    assert result["ok"] is True
    assert result["plan"]["contract"] == "magent.graph-plan.v2"
    assert [node["id"] for node in result["plan"]["nodes"]] == [
        "draft_contributing",
        "maintainer_approval",
    ]
    assert result["plan"]["nodes"][1]["dependencies"] == ["draft_contributing"]


def test_background_run_moves_cards_to_done_with_summaries(graph_project, monkeypatch) -> None:
    project, graph, store = graph_project
    monkeypatch.setattr(web_graphs, "load_config", lambda _username: Config(DEFAULT_GLOBAL_CONFIG))

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.emit = kwargs["event_sink"]

        async def run(self, _path, *, params):
            self.emit({"type": "graph.started", "run_id": "run_1", "state": "running"})
            for node_id, title in [
                ("draft_contributing", "Draft contributing guide"),
                ("maintainer_approval", "Maintainer approval"),
            ]:
                self.emit(
                    {
                        "type": "node.started",
                        "run_id": "run_1",
                        "node_id": node_id,
                        "state": "running",
                    }
                )
                self.emit(
                    {
                        "type": "node.completed",
                        "run_id": "run_1",
                        "node_id": node_id,
                        "state": "succeeded",
                        "summary": f"{title} completed.",
                    }
                )
            self.emit(
                {
                    "type": "graph.completed",
                    "run_id": "run_1",
                    "state": "succeeded",
                    "summary": "Graph succeeded.",
                }
            )
            return {
                "ok": True,
                "run": {
                    "run_id": "run_1",
                    "status": "succeeded",
                    "summary": {"text": "Graph succeeded."},
                },
            }

    monkeypatch.setattr(web_graphs, "GraphExecutor", FakeExecutor)
    manager = GraphRunManager(store, "alex", project)
    job = manager.start(str(graph), approved_gates=["maintainer_approval"])
    deadline = time.monotonic() + 2
    while job["state"] not in {"succeeded", "failed"} and time.monotonic() < deadline:
        time.sleep(0.01)
        job = manager.status(job["job_id"])

    assert job["state"] == "succeeded"
    assert all(node["state"] == "succeeded" for node in job["nodes"])
    assert all(node["summary"].endswith("completed.") for node in job["nodes"])
