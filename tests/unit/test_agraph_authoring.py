from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent.agraph.authoring import (
    CONTRACT_VERSION,
    authoring_contract,
    duplicate_node,
    generate_draft,
    inspect_graph,
    node_template,
    preview_graph,
    rename_node,
    save_graph,
)
from magent.cli.main import app


def test_authoring_contract_exposes_schema_and_profiles(tmp_path: Path) -> None:
    result = authoring_contract(tmp_path)
    assert result["contract"] == CONTRACT_VERSION
    assert "task" in result["node_types"]
    assert any(profile["name"] == "magagent" for profile in result["profiles"])
    assert result["schema"]["properties"]["nodes"]
    assert set(result["node_templates"]) == set(result["node_types"])


def test_generate_preview_save_inspect_and_conflict(tmp_path: Path) -> None:
    document = generate_draft("Add a verified command", project=tmp_path)["document"]
    document["nodes"]["implement"]["x-magagent-profile"] = "docs"
    preview = preview_graph(document, project=tmp_path)
    assert preview["ok"] is True
    assert preview["plan"]["contract"] == "magent.graph-plan.v2"
    assert preview["plan"]["order"] == ["inspect", "implement", "verify"]
    implement = next(item for item in preview["plan"]["nodes"] if item["id"] == "implement")
    assert implement["dependencies"] == ["inspect"]
    assert implement["initial_blocking"][0]["code"] == "GRAPH_DEPENDENCY_PENDING"
    assert implement["resolved_profile"]["name"] == "docs"

    saved = save_graph(document, "work.agraph.yaml", project=tmp_path)
    assert saved["ok"] is True
    loaded = inspect_graph(tmp_path / "work.agraph.yaml")
    assert loaded["document"]["nodes"]["implement"]["x-magagent-profile"] == "docs"

    changed = {**document, "title": "Changed elsewhere"}
    save_graph(changed, "work.agraph.yaml", project=tmp_path)
    conflict = save_graph(
        document, "work.agraph.yaml", project=tmp_path, expected_digest=saved["digest"]
    )
    assert conflict["ok"] is False
    assert conflict["conflict"] is True


def test_deterministic_web_research_draft_declares_real_capabilities(
    tmp_path: Path,
) -> None:
    document = generate_draft(
        "Research the history of sushi and create an HTML/CSS/JS website",
        project=tmp_path,
    )["document"]

    assert document["nodes"]["inspect"]["requirements"] == {
        "tools": ["file_read", "file_search", "web_search", "web_fetch"],
        "permissions": ["fs:read:**", "net:fetch:https://**"],
        "workspace": "read_only",
    }
    assert document["nodes"]["implement"]["requirements"] == {
        "tools": ["file_read", "file_search", "file_write", "shell_exec"],
        "permissions": ["fs:read:**", "fs:write:**", "shell:exec:*"],
        "workspace": "read_write",
    }
    assert preview_graph(document, project=tmp_path)["ok"] is True


def test_authoring_rejects_unknown_profile_and_escape(tmp_path: Path) -> None:
    document = generate_draft("Document the project", project=tmp_path)["document"]
    document["nodes"]["inspect"]["x-magagent-profile"] = "missing"
    preview = preview_graph(document, project=tmp_path)
    assert preview["ok"] is False
    assert any(item["code"] == "MAGP001" for item in preview["validation"]["findings"])

    document["nodes"]["inspect"].pop("x-magagent-profile")
    escaped = save_graph(document, tmp_path.parent / "escape.agraph.json", project=tmp_path)
    assert escaped == {"ok": False, "error": "Graph path escapes the active project"}


def test_all_node_templates_are_strictly_valid() -> None:
    for kind in ("task", "decision", "gate", "loop", "map", "subgraph"):
        document = {
            "ags_version": "1.0",
            "kind": "AgenticGraph",
            "id": f"test/{kind}",
            "title": kind,
            "objective": "Test template",
            "entrypoints": [kind],
            "constraints": {"max_cost_usd": 5.0},
            "nodes": {kind: node_template(kind)},
        }
        assert preview_graph(document)["ok"] is True, kind


def test_rename_and_duplicate_update_references() -> None:
    document = {
        "ags_version": "1.0",
        "kind": "AgenticGraph",
        "id": "test/rename",
        "title": "Rename",
        "objective": "Rename",
        "entrypoints": ["a"],
        "nodes": {
            "a": {
                **node_template("task"),
                "outputs": {"summary": {"type": "markdown", "description": "Result"}},
            },
            "b": {
                **node_template("task"),
                "depends_on": ["a"],
                "inputs": {
                    "result": {
                        "type": "markdown",
                        "description": "Result",
                        "from": "nodes.a.outputs.summary",
                    }
                },
            },
        },
    }
    renamed = rename_node(document, "a", "inspect")
    assert renamed["ok"] is True
    assert renamed["document"]["entrypoints"] == ["inspect"]
    assert renamed["document"]["nodes"]["b"]["depends_on"] == ["inspect"]
    assert (
        renamed["document"]["nodes"]["b"]["inputs"]["result"]["from"]
        == "nodes.inspect.outputs.summary"
    )
    duplicated = duplicate_node(renamed["document"], "inspect", "inspect_copy")
    assert duplicated["ok"] is True
    assert "inspect_copy" in duplicated["document"]["nodes"]


def test_graph_authoring_cli_round_trip(tmp_path: Path) -> None:
    runner = CliRunner()
    schema = runner.invoke(app, ["graph", "schema", "--project", str(tmp_path)])
    assert schema.exit_code == 0
    assert json.loads(schema.stdout)["node_templates"]["gate"]["gate"]["mode"] == "approve"

    document = generate_draft("Author a graph", project=tmp_path)["document"]
    preview = runner.invoke(
        app,
        ["graph", "preview", "--input", "-", "--project", str(tmp_path)],
        input=json.dumps(document),
    )
    assert preview.exit_code == 0
    target = tmp_path / "roundtrip.agraph.json"
    applied = runner.invoke(
        app,
        ["graph", "apply", str(target), "--input", "-", "--project", str(tmp_path)],
        input=json.dumps(document),
    )
    assert applied.exit_code == 0
    digest = json.loads(applied.stdout)["digest"]
    inspected = runner.invoke(app, ["graph", "inspect", str(target)])
    assert json.loads(inspected.stdout)["digest"] == digest
    renamed = runner.invoke(
        app,
        ["graph", "rename-node", "inspect", "audit", "--input", "-"],
        input=json.dumps(document),
    )
    assert renamed.exit_code == 0
    assert "audit" in json.loads(renamed.stdout)["document"]["nodes"]
