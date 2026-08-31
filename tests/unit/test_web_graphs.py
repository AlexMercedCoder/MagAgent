from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

import pytest

import magent.web_graphs as web_graphs
from magent.config import DEFAULT_GLOBAL_CONFIG, Config
from magent.web_graphs import (
    GraphDraftManager,
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


def test_graph_tool_event_becomes_safe_live_activity() -> None:
    assert (
        web_graphs._graph_event_activity(
            {
                "type": "node.tool.requested",
                "title": "Research sushi history",
                "state": "running",
                "tool": "web_fetch",
                "args": {"url": "https://secret.example/token"},
            }
        )
        == "Research sushi history requested the declared tool web_fetch."
    )


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


def test_graph_preview_rejects_invented_tool_with_canonical_suggestion(
    graph_project, monkeypatch
) -> None:
    project, _graph, _store = graph_project
    monkeypatch.setattr(web_graphs, "load_config", lambda _username: Config(DEFAULT_GLOBAL_CONFIG))
    document = blank_graph_document("Research sushi history")
    node = web_task_node()
    node["requirements"] = {
        "tools": ["net_fetch"],
        "permissions": ["net:fetch:https://**"],
        "workspace": "read_only",
    }
    document["nodes"] = {"research": node}
    document["entrypoints"] = ["research"]
    document["outputs"] = {
        "result": {
            "type": "markdown",
            "description": "Research result.",
            "from": "nodes.research.outputs.summary",
        }
    }

    result = preview_web_graph(document, project=project, username="alex")

    assert result["ok"] is False
    messages = [item["message"] for item in result["validation"]["findings"]]
    assert any("net_fetch" in message and "web_fetch" in message for message in messages)


def test_graph_preview_requires_network_permission_for_web_tools(
    graph_project, monkeypatch
) -> None:
    project, _graph, _store = graph_project
    monkeypatch.setattr(web_graphs, "load_config", lambda _username: Config(DEFAULT_GLOBAL_CONFIG))
    document = blank_graph_document("Research sushi history")
    node = web_task_node()
    node["requirements"] = {
        "tools": ["web_search", "web_fetch"],
        "permissions": ["fs:read:**"],
        "workspace": "read_only",
    }
    document["nodes"] = {"research": node}
    document["entrypoints"] = ["research"]
    document["outputs"] = {
        "result": {
            "type": "markdown",
            "description": "Research result.",
            "from": "nodes.research.outputs.summary",
        }
    }

    result = preview_web_graph(document, project=project, username="alex")

    assert result["ok"] is False
    messages = [item["message"] for item in result["validation"]["findings"]]
    assert any("net" in message and "web_fetch" in message for message in messages)


@pytest.mark.asyncio
async def test_ai_graph_generation_uses_review_only_model_contract(
    graph_project, monkeypatch
) -> None:
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


def test_background_draft_reports_safe_progress(graph_project, monkeypatch) -> None:
    project, _graph, _store = graph_project

    async def fake_generate(goal, **kwargs):
        kwargs["progress"](
            {
                "stage": "requesting",
                "message": "The planning model is drafting the graph.",
                "attempt": 1,
            }
        )
        kwargs["progress"](
            {
                "stage": "validated",
                "message": "The generated graph passed strict AGS validation.",
                "attempt": 1,
            }
        )
        return {"ok": True, "document": {"id": "generated", "nodes": {}}}

    monkeypatch.setattr(web_graphs, "generate_web_graph", fake_generate)
    manager = GraphDraftManager(project, "alex")
    job = manager.start("Build a small site")
    deadline = time.monotonic() + 2
    while job["status"] not in {"succeeded", "failed"} and time.monotonic() < deadline:
        time.sleep(0.01)
        job = manager.status(job["job_id"])

    assert job["status"] == "succeeded"
    assert [event["stage"] for event in job["activity"]] == ["requesting", "validated"]
    assert job["result"]["document"]["id"] == "generated"
    assert all("reasoning" not in event for event in job["activity"])


def test_background_draft_can_cancel_an_active_provider_request(graph_project, monkeypatch) -> None:
    project, _graph, _store = graph_project

    async def fake_generate(_goal, **kwargs):
        kwargs["progress"]({"stage": "requesting", "message": "Waiting for provider."})
        await asyncio.sleep(30)
        return {"ok": True, "document": {"id": "too-late"}}

    monkeypatch.setattr(web_graphs, "generate_web_graph", fake_generate)
    manager = GraphDraftManager(project, "alex")
    job = manager.start("Build a small site")
    deadline = time.monotonic() + 2
    while job["status"] == "queued" and time.monotonic() < deadline:
        time.sleep(0.01)
        job = manager.status(job["job_id"])

    cancelled = manager.cancel(job["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["result"]["error"] == "Graph generation was cancelled."


@pytest.mark.asyncio
async def test_model_graph_draft_timeout_returns_capability_aware_fallback(
    monkeypatch, tmp_path
) -> None:
    import magent.agraph.authoring as authoring
    import magent.cli.command_context as command_context

    class StalledProvider:
        display_name = "stalled-test-provider"

        async def complete(self, *_args, **_kwargs):
            await asyncio.sleep(30)
            return "{}"

    monkeypatch.setattr(
        command_context, "build_provider_for_role", lambda *_args: StalledProvider()
    )
    monkeypatch.setattr(authoring, "MODEL_ATTEMPT_TIMEOUT_SECONDS", 0.01)
    events = []
    result = await authoring.model_graph_draft(
        "research the history of sushi and then create an html/css/js website",
        project=tmp_path,
        config=Config(DEFAULT_GLOBAL_CONFIG),
        progress=events.append,
    )

    assert result["ok"] is True
    assert result["fallback"] is True
    assert [event["stage"] for event in events].count("timeout") == 1
    assert events[-1]["stage"] == "fallback"
    nodes = result["document"]["nodes"]
    assert nodes["inspect"]["requirements"]["tools"] == [
        "file_read",
        "file_search",
        "web_search",
        "web_fetch",
    ]
    assert "net:fetch:https://**" in nodes["inspect"]["requirements"]["permissions"]
    assert "file_write" in nodes["implement"]["requirements"]["tools"]


@pytest.mark.asyncio
async def test_model_graph_draft_repairs_invented_tool_name(monkeypatch, tmp_path) -> None:
    import magent.agraph.authoring as authoring
    import magent.cli.command_context as command_context

    valid = blank_graph_document("Research sushi history")
    node = web_task_node()
    node["requirements"] = {
        "tools": ["web_search", "web_fetch"],
        "permissions": ["net:fetch:https://**"],
        "workspace": "read_only",
    }
    valid["nodes"] = {"research": node}
    valid["entrypoints"] = ["research"]
    valid["outputs"] = {
        "result": {
            "type": "markdown",
            "description": "Research result.",
            "from": "nodes.research.outputs.summary",
        }
    }
    invalid = json.loads(json.dumps(valid).replace('"web_fetch"', '"net_fetch"'))

    class RepairingProvider:
        display_name = "repairing-test-provider"

        def __init__(self):
            self.calls: list[str] = []

        async def complete(self, messages, **_kwargs):
            self.calls.append(json.dumps(messages))
            return json.dumps(invalid if len(self.calls) == 1 else valid)

    provider = RepairingProvider()
    monkeypatch.setattr(command_context, "build_provider_for_role", lambda *_args: provider)
    events = []

    result = await authoring.model_graph_draft(
        "Research sushi history",
        project=tmp_path,
        config=Config(DEFAULT_GLOBAL_CONFIG),
        progress=events.append,
    )

    assert result["ok"] is True
    assert result["document"]["nodes"]["research"]["requirements"]["tools"] == [
        "web_search",
        "web_fetch",
    ]
    assert "allowed_logical_tools" in provider.calls[0]
    assert "Did you mean 'web_fetch'" in provider.calls[1]
    assert [event["stage"] for event in events].count("repairing") == 1


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
                        "type": "node.tool.requested",
                        "run_id": "run_1",
                        "node_id": node_id,
                        "title": title,
                        "state": "running",
                        "tool": "read_file",
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
    assert job["activity"] == "Graph execution finished with status succeeded."
    assert any(event["type"] == "node.tool.requested" for event in job["events"])


def test_background_graph_permission_is_answered_from_browser(graph_project, monkeypatch) -> None:
    project, graph, store = graph_project
    monkeypatch.setattr(web_graphs, "load_config", lambda _username: Config(DEFAULT_GLOBAL_CONFIG))
    outcome: dict[str, str] = {}

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.permission_prompt = kwargs["permission_prompt"]

        async def run(self, _path, *, params):
            outcome["decision"] = self.permission_prompt("Run: `npm test`", 2)
            outcome["repeated_decision"] = self.permission_prompt("Run: `npm test`", 2)
            return {
                "ok": True,
                "run": {"run_id": "run_approval", "status": "succeeded", "summary": {}},
            }

    monkeypatch.setattr(web_graphs, "GraphExecutor", FakeExecutor)
    manager = GraphRunManager(store, "alex", project)
    job = manager.start(str(graph), approved_gates=["maintainer_approval"])
    deadline = time.monotonic() + 2
    while not job.get("awaiting_approvals") and time.monotonic() < deadline:
        time.sleep(0.01)
        job = manager.status(job["job_id"])

    request = job["awaiting_approvals"][0]
    assert request["choices"] == ["once", "session", "always", "deny"]
    assert manager.decide_approval(job["job_id"], request["request_id"], "session") is True

    while job["state"] not in {"succeeded", "failed"} and time.monotonic() < deadline:
        time.sleep(0.01)
        job = manager.status(job["job_id"])
    assert job["state"] == "succeeded"
    assert outcome["decision"] == "session"
    assert outcome["repeated_decision"] == "session"
    assert job["awaiting_approvals"] == []
    assert sum(event["type"] == "approval.requested" for event in job["events"]) == 1
