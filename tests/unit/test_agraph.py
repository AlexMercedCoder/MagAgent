from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from magent.agraph.criteria import evaluate_criteria
from magent.agraph.document import GraphDocumentError, load_graph
from magent.agraph.ecosystem import export_plugin_pack
from magent.agraph.execute import GraphExecutor, GraphRunError, _retry_closure
from magent.agraph.expressions import AgxEvaluationError, evaluate_expression
from magent.agraph.generate import generate_and_validate
from magent.agraph.output import emit_output
from magent.agraph.plan import plan_graph
from magent.agraph.record import validate_run_record
from magent.agraph.runtime_context import (
    GraphToolPolicy,
    authorize_graph_tool,
    reset_graph_tool_policy,
    set_graph_tool_policy,
)
from magent.agraph.status import graph_status
from magent.agraph.validate import validate_graph
from magent.config import DEFAULT_GLOBAL_CONFIG, Config
from magent.plugin_sdk import validate_plugin
from magent.workbench_store import WorkbenchStore

ROOT = Path(__file__).resolve().parents[2]


def graph(*, nodes: dict | None = None, outputs: dict | None = None, level: int = 1) -> dict:
    return {
        "ags_version": "1.0",
        "kind": "AgenticGraph",
        "id": "tests/runtime",
        "title": "Runtime test",
        "objective": "Exercise the graph runtime.",
        "version": "1.0.0",
        "requires_conformance": level,
        "entrypoints": [next(iter(nodes or {"work": {}}))],
        "nodes": nodes
        or {
            "work": {
                "type": "task",
                "title": "Do work",
                "description": "Produce a bounded result.",
                "outputs": {"result": {"type": "string", "description": "The result."}},
                "requirements": {"tools": [], "permissions": []},
                "success": {
                    "summary": "A result exists.",
                    "criteria": [
                        {
                            "id": "result",
                            "kind": "artifact_present",
                            "description": "Result emitted.",
                            "output": "result",
                        }
                    ],
                },
            }
        },
        "outputs": outputs
        or {
            "result": {
                "type": "string",
                "description": "Final result.",
                "from": "nodes.work.outputs.result",
            }
        },
    }


def executor(tmp_path: Path, runner, **kwargs) -> GraphExecutor:
    return GraphExecutor(
        username="test",
        config=Config(DEFAULT_GLOBAL_CONFIG),
        project=tmp_path,
        store=WorkbenchStore(tmp_path / "store"),
        agent_runner=runner,
        **kwargs,
    )


def test_document_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "bad.agraph.yaml"
    path.write_text("ags_version: '1.0'\nags_version: '1.0'\n", encoding="utf-8")
    with pytest.raises(GraphDocumentError, match="duplicate key"):
        load_graph(path)


@pytest.mark.parametrize("path", sorted((ROOT / "tests/fixtures/agraph_invalid").glob("*")))
def test_official_invalid_fixtures_report_expected_code(path: Path) -> None:
    expected = re.search(r"# EXPECT: (AG\d+)", path.read_text(encoding="utf-8")).group(1)
    assert expected in {item.code for item in validate_graph(path).findings}


@pytest.mark.parametrize("path", sorted((ROOT / "docs/examples/agraph").glob("*.agraph.*")))
def test_official_examples_validate(path: Path) -> None:
    assert validate_graph(path).ok, path


def test_expression_language_is_strict_and_has_no_host_eval() -> None:
    assert (
        evaluate_expression("len(items) == 2 && contains(items, 'a')", {"items": ["a", "b"]})
        is True
    )
    assert (
        evaluate_expression("default(nodes.optional.outputs.value, 'fallback')", {"nodes": {}})
        == "fallback"
    )
    assert (
        evaluate_expression(
            "default(nodes.present.outputs.value, 'fallback')",
            {"nodes": {"present": {"outputs": {"value": "kept"}}}},
        )
        == "kept"
    )
    with pytest.raises(AgxEvaluationError):
        evaluate_expression("1 == '1'", {})
    with pytest.raises(AgxEvaluationError):
        evaluate_expression("__import__('os')", {})


def test_optional_graph_output_may_reference_an_inactive_branch(tmp_path: Path) -> None:
    document = graph(
        outputs={
            "result": {
                "type": "string",
                "description": "Required result.",
                "from": "nodes.work.outputs.result",
            },
            "optional": {
                "type": "string",
                "description": "Optional branch result.",
                "from": "nodes.inactive.outputs.value",
                "required": False,
            },
        }
    )
    document["nodes"]["inactive"] = {
        "type": "task",
        "title": "Inactive branch",
        "description": "This branch is deliberately skipped.",
        "when": "false",
        "outputs": {"value": {"type": "string", "description": "Unused value."}},
        "requirements": {"tools": [], "permissions": []},
        "success": {
            "summary": "A value exists when active.",
            "criteria": [
                {
                    "id": "value",
                    "kind": "artifact_present",
                    "description": "Value emitted.",
                    "output": "value",
                }
            ],
        },
    }
    document["edges"] = [{"from": "work", "to": "inactive", "kind": "sequence"}]

    async def runner(*_args):
        emit_output("result", "done")
        return ""

    result = asyncio.run(executor(tmp_path, runner).run(document))
    assert result["ok"], (
        result["run"]["diagnostics"],
        result["run"]["nodes"],
        result["run"]["outputs"],
    )
    assert result["run"]["outputs"] == {"result": "done"}


def test_plan_is_deterministic_and_generated_graph_is_strictly_valid() -> None:
    first = plan_graph(ROOT / "docs/examples/agraph/minimal.agraph.yaml")
    second = plan_graph(ROOT / "docs/examples/agraph/minimal.agraph.yaml")
    assert first.order == second.order == ("draft_contributing", "maintainer_approval")
    generated, report = generate_and_validate("Repair tests and document the fix")
    assert report.ok
    assert "project_scan" in generated["context"]
    assert "repository_map" in generated["context"]


def test_cross_harness_minimal_golden_plan() -> None:
    golden = json.loads((ROOT / "docs/conformance/ags-golden-minimal.json").read_text())
    document = load_graph(ROOT / "docs/examples/agraph/minimal.agraph.yaml")
    plan = plan_graph(ROOT / "docs/examples/agraph/minimal.agraph.yaml")
    assert document.digest == golden["graph_digest"]
    assert list(plan.order) == golden["topological_order"]


def test_generated_graph_completes_real_scheduler_execution(tmp_path: Path) -> None:
    generated, report = generate_and_validate(
        "Create a small verified project artifact", project=tmp_path
    )
    assert report.ok

    async def generated_runner(node_id, _prompt, _route, _task_id):
        outputs = {
            "inspect": {"findings": "Use the existing project conventions."},
            "implement": {"summary": "Created the requested artifact."},
            "verify": {"report": "Verified the artifact and reviewed the result."},
        }
        return {"outputs": outputs[node_id]}

    graph_executor = executor(tmp_path, generated_runner)
    result = asyncio.run(graph_executor.run(generated))

    assert result["ok"] is True
    assert result["run"]["status"] == "succeeded"
    assert [node["node_id"] for node in result["run"]["nodes"]] == [
        "inspect",
        "implement",
        "verify",
    ]
    assert result["run"]["outputs"]["verification_report"].startswith("Verified")
    assert result["run"]["metadata"]["graph_snapshot"]["id"] == generated["id"]
    child_tasks = graph_executor.runtime.list_tasks(parent_task_id=result["task_id"])
    assert {task["metadata"]["node_id"] for task in child_tasks} == {
        "inspect",
        "implement",
        "verify",
    }


def test_parallel_nodes_keep_profile_context_isolated(tmp_path: Path) -> None:
    nodes = {
        "docs": {
            "type": "task",
            "title": "Docs",
            "description": "Write docs.",
            "x-magagent-profile": "docs",
            "outputs": {"result": {"type": "string", "description": "Result."}},
            "requirements": {"tools": [], "permissions": []},
            "success": {
                "criteria": [
                    {
                        "id": "done",
                        "kind": "artifact_present",
                        "description": "Done.",
                        "output": "result",
                    }
                ]
            },
        },
        "code": {
            "type": "task",
            "title": "Code",
            "description": "Write code.",
            "x-magagent-profile": "code",
            "outputs": {"result": {"type": "string", "description": "Result."}},
            "requirements": {"tools": [], "permissions": []},
            "success": {
                "criteria": [
                    {
                        "id": "done",
                        "kind": "artifact_present",
                        "description": "Done.",
                        "output": "result",
                    }
                ]
            },
        },
    }
    document = graph(
        nodes=nodes,
        outputs={
            "docs": {"type": "string", "description": "Docs.", "from": "nodes.docs.outputs.result"},
            "code": {"type": "string", "description": "Code.", "from": "nodes.code.outputs.result"},
        },
    )
    document["entrypoints"] = ["docs", "code"]
    document["constraints"] = {"max_parallel_nodes": 2}
    seen: dict[str, str] = {}
    graph_executor: GraphExecutor

    async def runner(node, _prompt, _route, _task):
        await asyncio.sleep(0.01)
        seen[node] = graph_executor._active_profile.get().name
        emit_output("result", node)
        return ""

    graph_executor = executor(tmp_path, runner)
    graph_executor.config._global["subagents"]["max_parallel"] = 2
    graph_executor._profile_for_node = lambda node: SimpleNamespace(name=node["x-magagent-profile"])
    result = asyncio.run(graph_executor.run(document))
    assert result["ok"] is True
    assert seen == {"docs": "docs", "code": "code"}


def test_durable_pause_waits_at_node_boundary(tmp_path: Path) -> None:
    second = {
        "type": "task",
        "title": "Second",
        "description": "Second.",
        "depends_on": ["work"],
        "inputs": {
            "prior": {
                "type": "string",
                "description": "First result.",
                "from": "nodes.work.outputs.result",
            }
        },
        "outputs": {"result": {"type": "string", "description": "Result."}},
        "requirements": {"tools": [], "permissions": []},
        "success": {
            "criteria": [
                {
                    "id": "done",
                    "kind": "artifact_present",
                    "description": "Done.",
                    "output": "result",
                }
            ]
        },
    }
    document = graph(
        nodes={**graph()["nodes"], "second": second},
        outputs={
            "result": {
                "type": "string",
                "description": "Final.",
                "from": "nodes.second.outputs.result",
            }
        },
    )
    calls: list[str] = []

    async def scenario() -> dict:
        nonlocal graph_executor

        async def runner(node, _prompt, _route, _task):
            calls.append(node)
            await asyncio.sleep(0.03)
            emit_output("result", node)
            return ""

        store = WorkbenchStore(tmp_path / "pause-store")
        runtime_task = GraphExecutor(
            username="test",
            config=Config(DEFAULT_GLOBAL_CONFIG),
            project=tmp_path,
            store=store,
            agent_runner=runner,
        )
        root = runtime_task.runtime.create("agentic_graph", "Pause", project=tmp_path)
        graph_executor = GraphExecutor(
            username="test",
            config=Config(DEFAULT_GLOBAL_CONFIG),
            project=tmp_path,
            store=store,
            agent_runner=runner,
            root_task_id=root["id"],
        )
        running = asyncio.create_task(graph_executor.run(document))
        await asyncio.sleep(0.01)
        graph_executor.runtime.pause(root["id"])
        await asyncio.sleep(0.06)
        assert calls == ["work"] and not running.done()
        graph_executor.runtime.resume(root["id"])
        return await running

    graph_executor: GraphExecutor
    result = asyncio.run(scenario())
    assert result["ok"] is True and calls == ["work", "second"]


def test_generation_eval_corpus_meets_quality_floor() -> None:
    corpus = json.loads((ROOT / "evals/agentic-graph-generation.json").read_text(encoding="utf-8"))
    reports = [generate_and_validate(goal, strict=True)[1] for goal in corpus["goals"]]
    rate = sum(report.ok for report in reports) / len(reports)
    assert rate >= corpus["targets"]["strict_validation_rate"]


def test_simple_execution_emits_valid_record_and_resume_reuses_success(tmp_path: Path) -> None:
    calls = 0
    events: list[dict] = []

    async def runner(_node, _prompt, _route, _task):
        nonlocal calls
        calls += 1
        emit_output("result", "done")
        return ""

    first_executor = executor(tmp_path, runner, event_sink=events.append)
    first = asyncio.run(first_executor.run(graph()))
    validate_run_record(first["run"])
    second = asyncio.run(executor(tmp_path, runner).run(graph(), resume_record=first["run"]))
    assert first["ok"] and second["ok"]
    assert calls == 1
    assert second["run"]["outputs"] == {"result": "done"}
    assert first["run"]["metadata"]["x-magagent-summary"] == {
        "text": "Graph succeeded: 1 succeeded, 0 failed or blocked, 0 skipped.",
        "succeeded": ["work"],
        "failed": [],
        "skipped": [],
        "total": 1,
    }
    assert [event["type"] for event in events] == [
        "graph.started",
        "node.queued",
        "node.started",
        "node.completed",
        "graph.completed",
    ]
    assert all(event["schema_version"] == "magent.graph-event.v1" for event in events)
    snapshot = graph_status(first_executor.store, first["run"]["run_id"])
    assert snapshot and snapshot["schema_version"] == "magent.graph-status.v1"
    assert snapshot["nodes"][0]["state"] == "succeeded"
    assert snapshot["nodes"][0]["summary"] == "done"


def test_selective_retry_invalidates_selected_job_and_dependents() -> None:
    document = graph(
        nodes={
            "inspect": {"type": "task"},
            "implement": {"type": "task", "depends_on": ["inspect"]},
            "verify": {"type": "task", "depends_on": ["implement"]},
            "docs": {"type": "task", "depends_on": ["inspect"]},
        }
    )
    assert _retry_closure(document, {"implement"}) == {"implement", "verify"}


def test_expression_decision_activates_only_selected_branch(tmp_path: Path) -> None:
    nodes = {
        "choose": {
            "type": "decision",
            "title": "Choose",
            "description": "Select one branch.",
            "decision": {
                "evaluator": "expression",
                "branches": [
                    {
                        "label": "yes",
                        "description": "Enabled path.",
                        "when": "params.enabled == true",
                    },
                    {
                        "label": "no",
                        "description": "Disabled path.",
                        "when": "params.enabled == false",
                    },
                ],
            },
        },
        "yes": {
            "type": "task",
            "title": "Yes",
            "description": "Emit yes.",
            "outputs": {"value": {"type": "string", "description": "Value."}},
            "requirements": {"tools": [], "permissions": []},
            "success": {
                "summary": "Done.",
                "criteria": [
                    {
                        "id": "value",
                        "kind": "artifact_present",
                        "description": "Value.",
                        "output": "value",
                    }
                ],
            },
        },
        "no": {
            "type": "task",
            "title": "No",
            "description": "Emit no.",
            "outputs": {"value": {"type": "string", "description": "Value."}},
            "requirements": {"tools": [], "permissions": []},
            "success": {
                "summary": "Done.",
                "criteria": [
                    {
                        "id": "value",
                        "kind": "artifact_present",
                        "description": "Value.",
                        "output": "value",
                    }
                ],
            },
        },
    }
    document = graph(
        nodes=nodes,
        outputs={
            "value": {
                "type": "string",
                "description": "Chosen value.",
                "from": "nodes.yes.outputs.value",
            }
        },
        level=2,
    )
    document["params"] = {"enabled": {"type": "boolean", "description": "Choose yes."}}
    document["edges"] = [
        {
            "from": "choose",
            "to": "yes",
            "kind": "conditional",
            "when": "nodes.choose.outputs.decision == 'yes'",
        },
        {
            "from": "choose",
            "to": "no",
            "kind": "conditional",
            "when": "nodes.choose.outputs.decision == 'no'",
        },
    ]
    calls = []

    async def runner(node, _prompt, _route, _task):
        calls.append(node)
        emit_output("value", "yes")
        return ""

    result = asyncio.run(executor(tmp_path, runner).run(document, params={"enabled": True}))
    assert result["ok"], (result["run"]["diagnostics"], result["run"]["nodes"])
    assert calls == ["yes"]


def test_human_checkpoints_and_graph_tool_policy(tmp_path: Path) -> None:
    document = graph()
    document["nodes"]["work"]["human"] = [
        {"id": "start", "at": "before_start", "mode": "approve", "prompt": "Start?"},
        {"id": "review", "at": "after_outputs", "mode": "review", "prompt": "Accept?"},
    ]
    approvals = []

    async def approve(prompt, _detail):
        approvals.append(prompt)
        return True

    async def runner(_node, _prompt, _route, _task):
        emit_output("result", "done")
        return ""

    result = asyncio.run(executor(tmp_path, runner, approval=approve).run(document))
    assert approvals == ["Start?", "Accept?"]
    assert len(result["run"]["nodes"][0]["human_events"]) == 2

    policy = GraphToolPolicy({"read_file"}, ("fs:read:**",))
    token = set_graph_tool_policy(policy)
    try:
        assert asyncio.run(authorize_graph_tool("read_file", {"path": "README.md"}, str(tmp_path)))[
            "ok"
        ]
        assert (
            "RT012"
            in asyncio.run(authorize_graph_tool("write_file", {"path": "x"}, str(tmp_path)))[
                "error"
            ]
        )
    finally:
        reset_graph_tool_policy(token)


def test_worktree_isolation_refuses_non_git_project(tmp_path: Path) -> None:
    document = graph()
    document["nodes"]["work"]["constraints"] = {"isolation": "worktree"}

    async def runner(*_args):
        emit_output("result", "done")
        return ""

    result = asyncio.run(executor(tmp_path, runner).run(document))
    assert not result["ok"]
    assert any("RT014" in item["message"] for item in result["run"]["diagnostics"])


def test_resume_rejects_changed_digest(tmp_path: Path) -> None:
    async def runner(*_args):
        emit_output("result", "done")
        return ""

    first = asyncio.run(executor(tmp_path, runner).run(graph()))
    changed = graph()
    changed["title"] = "Changed"
    with pytest.raises(GraphRunError, match="RT053"):
        asyncio.run(executor(tmp_path, runner).run(changed, resume_record=first["run"]))


def test_external_subgraph_uses_uri_params_and_output_mapping(tmp_path: Path) -> None:
    child = graph(
        outputs={
            "result": {
                "type": "string",
                "description": "Child result.",
                "from": "nodes.work.outputs.result",
            }
        }
    )
    child["id"] = "tests/child"
    child["params"] = {"label": {"type": "string", "description": "Value to emit."}}
    child["nodes"]["work"]["inputs"] = {
        "label": {"type": "string", "description": "Value to emit.", "from": "params.label"}
    }
    child_path = tmp_path / "child.agraph.yaml"
    from magent.agraph.document import write_graph

    write_graph(child, child_path)
    parent = graph(
        nodes={
            "child": {
                "type": "subgraph",
                "title": "Run child",
                "description": "Execute the child graph.",
                "subgraph": {
                    "ref": {"uri": "./child.agraph.yaml", "expected_id": "tests/child"},
                    "params": {"label": "params.label"},
                    "outputs_from": {"value": "outputs.result"},
                },
            }
        },
        outputs={
            "value": {
                "type": "string",
                "description": "Mapped child value.",
                "from": "nodes.child.outputs.value",
            }
        },
        level=3,
    )
    parent["params"] = {"label": {"type": "string", "description": "Value for child."}}
    parent_path = tmp_path / "parent.agraph.yaml"
    write_graph(parent, parent_path)

    async def runner(_node, prompt, _route, _task):
        assert '"label": "hello"' in prompt
        emit_output("result", "hello")
        return ""

    result = asyncio.run(executor(tmp_path, runner).run(parent_path, params={"label": "hello"}))
    assert result["ok"], (result["run"]["diagnostics"], result["run"]["nodes"])
    assert result["run"]["outputs"] == {"value": "hello"}


def test_run_record_redacts_declared_values_and_environment_secrets(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DEPLOY_TOKEN", "super-secret-value")
    document = graph()
    document["secrets"] = [
        {"name": "deploy_token", "description": "Deployment credential.", "required": True}
    ]
    document["nodes"]["work"]["outputs"]["result"]["redact"] = True

    async def runner(*_args):
        emit_output("result", "super-secret-value")
        return ""

    result = asyncio.run(executor(tmp_path, runner).run(document))
    encoded = json.dumps(result["run"])
    assert result["ok"]
    assert "super-secret-value" not in encoded
    assert "[REDACTED]" in encoded


def test_retry_policy_does_not_retry_unlisted_failure_class(tmp_path: Path) -> None:
    document = graph()
    document["nodes"]["work"]["failure"] = {
        "retry": {"max_attempts": 3, "retry_on": ["timeout"], "backoff": "none"},
        "on_exhausted": "fail",
    }
    calls = 0

    async def runner(*_args):
        nonlocal calls
        calls += 1
        raise RuntimeError("tool failed")

    result = asyncio.run(executor(tmp_path, runner).run(document))
    assert not result["ok"]
    assert calls == 1


def test_exported_graph_plugin_pack_is_native_and_valid(tmp_path: Path) -> None:
    exported = export_plugin_pack(tmp_path / "plugin")
    report = validate_plugin(exported["root"], strict=True)
    assert exported["manifest"].endswith("magent-plugin.toml")
    assert report["ok"], report
    assert {"agentic_graph", "schemas"}.issubset(report["manifest"]["capabilities"])


def test_usage_telemetry_is_recorded_and_token_budget_is_enforced(tmp_path: Path) -> None:
    document = graph()
    document["nodes"]["work"]["constraints"] = {"max_total_tokens": 10}

    async def runner(*_args):
        return {
            "outputs": {"result": "done"},
            "_usage": {
                "prompt_tokens": 8,
                "completion_tokens": 5,
                "total_tokens": 13,
                "cost_usd": 0.01,
                "turns": 1,
            },
        }

    result = asyncio.run(executor(tmp_path, runner).run(document))
    assert not result["ok"]
    assert result["run"]["usage"]["total_tokens"] == 13
    assert any(item["code"] == "RT030" for item in result["run"]["diagnostics"])


def test_success_criteria_modes_count_only_required_checks(tmp_path: Path) -> None:
    criteria = [
        {"id": "pass", "kind": "expression", "description": "Pass.", "expr": "true"},
        {"id": "fail", "kind": "expression", "description": "Fail.", "expr": "false"},
        {
            "id": "advice",
            "kind": "expression",
            "description": "Advice.",
            "expr": "false",
            "severity": "advisory",
        },
    ]
    any_ok, _ = asyncio.run(
        evaluate_criteria(criteria, outputs={}, scope={}, project=tmp_path, mode="any")
    )
    two_ok, _ = asyncio.run(
        evaluate_criteria(criteria, outputs={}, scope={}, project=tmp_path, mode="n_of", count=2)
    )
    assert any_ok
    assert not two_ok


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / "docs/examples/agraph").glob("*.agraph.yaml")),
)
def test_packaged_yaml_examples_complete_structural_execution(
    path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise real scheduling and composition without provider calls or side effects."""
    from magent.agraph.routing import Route

    monkeypatch.setattr(
        "magent.agraph.execute.route_for_node",
        lambda _config, node: Route(
            str((node.get("intelligence") or {}).get("tier", "standard")),
            str((node.get("intelligence") or {}).get("tier", "standard")),
            "coding",
            "test",
            "structural",
        ),
    )

    class StructuralExecutor(GraphExecutor):
        async def _criteria(self, *_args, **_kwargs):
            return True, []

    values = {
        "array": [],
        "file_set": [],
        "integer": 0,
        "number": 0,
        "boolean": True,
        "object": {},
        "json": {},
    }

    async def runner(_node, prompt, _route, _task):
        if "Labels:" in prompt:
            labels_text, outputs_text = prompt.split("Labels:", 1)[1].split(
                "\nDeclared outputs:", 1
            )
            decision_outputs = json.loads(outputs_text.strip())
            return {
                "decision": json.loads(labels_text.strip())[0],
                "outputs": {
                    name: values.get(str(spec.get("type", "string")), "ok")
                    for name, spec in decision_outputs.items()
                },
            }
        contract = json.loads(
            prompt.split("Declared outputs:\n", 1)[1].split("\n\nComplete the task", 1)[0]
        )
        return {
            "outputs": {
                name: values.get(str(spec.get("type", "string")), "ok")
                for name, spec in contract.items()
            }
        }

    runner_executor = StructuralExecutor(
        username="test",
        config=Config(DEFAULT_GLOBAL_CONFIG),
        project=tmp_path,
        store=WorkbenchStore(tmp_path / "store"),
        agent_runner=runner,
        assume_yes=True,
    )
    document = load_graph(path)
    for secret in document.data.get("secrets") or []:
        name = str(secret.get("name", "") if isinstance(secret, dict) else secret)
        if name:
            monkeypatch.setenv(name.upper(), "structural-test-secret")
    params = {
        name: values.get(str(spec.get("type", "string")), "test-value")
        for name, spec in (document.data.get("params") or {}).items()
        if spec.get("required", True) and "default" not in spec
    }
    result = asyncio.run(runner_executor.run(document, params=params))
    assert result["ok"], (path.name, result["run"]["diagnostics"], result["run"]["nodes"])
