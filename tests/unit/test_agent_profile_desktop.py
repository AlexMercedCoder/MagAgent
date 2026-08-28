from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from magent.agent_profiles.authoring import build_profile_document
from magent.agent_profiles.desktop import (
    PROFILE_CONTRACT,
    apply_profile,
    clone_profile,
    delete_profile,
    export_profile,
    inspect_profile,
    preview_profile,
    profile_checkpoints,
    profile_contract,
    rollback_profile,
)
from magent.agent_profiles.registry import AgentProfileRegistry
from magent.cli import main as cli_main
from magent.workbench_store import WorkbenchStore


class Config:
    permission_mode = "balanced"
    default_provider = "nous-portal"
    default_model = "deepseek-v4-flash"
    memory_budget_tokens = 4000
    memory_mode = "read_write"
    max_subagents = 3
    max_parallel_subagents = 2
    mcp_servers = {"servers": {"github": {"transport": "stdio"}}}

    def get(self, *parts, default=None):
        values = {
            ("agent", "max_model_rounds_per_turn"): 16,
            ("agent_profiles", "max_state_tokens"): 1200,
            ("agent_profiles", "writeback"): "propose",
            ("agent_profiles", "max_delegation_depth"): 3,
            ("tool_budgets",): {},
            ("budgets", "session_usd"): 5.0,
        }
        return values.get(parts, default)


def document(name: str = "researcher") -> dict:
    return build_profile_document(
        name=name,
        description="Researches with citations",
        annotations={"dev.magcommandcenter.color": "teal"},
        role={"instructions": "Research carefully and cite sources."},
        tools={"allow": ["read", "web"], "mcp_servers": ["github"]},
        permissions={"default": "balanced", "network": "read"},
        memory={"mode": "read"},
        runtime={"max_turns": 8, "subagents": {"allow": ["review"]}},
    )


def test_contract_contains_schema_choices_templates_and_boundary(tmp_path: Path) -> None:
    result = profile_contract(tmp_path, Config())

    assert result["ok"] is True
    assert result["contract"] == PROFILE_CONTRACT
    assert result["schema"]["properties"]["spec"]["properties"]["permissions"]
    assert "read" in result["choices"]["network_modes"]
    assert any(item["id"] == "coder" for item in result["templates"])
    assert "not a user account" in result["guidance"]["profile_boundary"]


def test_preview_reports_effective_policy_and_missing_dependencies(tmp_path: Path) -> None:
    valid = preview_profile(document(), project=tmp_path, config=Config())
    broken = document("broken")
    broken["spec"]["tools"]["skills"] = ["not-installed"]
    invalid = preview_profile(broken, project=tmp_path, config=Config())

    assert valid["ok"] is True
    assert valid["effective_profile"]["network_access"] == "read"
    assert "http_request" not in valid["effective_profile"]["tools"]
    assert invalid["ok"] is True
    assert invalid["ready"] is False
    assert invalid["dependencies"]["missing"]["skills"] == ["not-installed"]


def test_apply_update_clone_export_and_delete_are_guarded(tmp_path: Path) -> None:
    created = apply_profile(document(), scope="project", project=tmp_path, config=Config())
    digest = created["profile"]["profile_digest"]
    changed = document()
    changed["metadata"]["description"] = "Updated description"

    rejected = apply_profile(changed, scope="project", project=tmp_path, config=Config())
    updated = apply_profile(
        changed,
        scope="project",
        project=tmp_path,
        config=Config(),
        expected_digest=digest,
    )
    cloned = clone_profile(
        "researcher", "research-copy", scope="project", project=tmp_path, config=Config()
    )
    exported = export_profile(
        "researcher", tmp_path / "exported.md", project=tmp_path, config=Config()
    )
    wrong_delete = delete_profile(
        "research-copy", project=tmp_path, config=Config(), expected_digest="wrong"
    )
    deleted = delete_profile(
        "research-copy",
        project=tmp_path,
        config=Config(),
        expected_digest=cloned["profile"]["profile_digest"],
    )

    assert created["operation"] == "create"
    assert rejected["conflict"] is True
    assert updated["operation"] == "update"
    assert updated["profile"]["revision"] == 2
    reloaded = AgentProfileRegistry(tmp_path, Config()).get("researcher")
    assert reloaded is not None
    assert reloaded.document["history"][-1]["by"] == "magagent-desktop"
    assert cloned["ok"] is True
    assert exported["secrets_included"] is False
    assert (tmp_path / "exported.md").exists()
    assert wrong_delete["conflict"] is True
    assert deleted["ok"] is True


def test_profile_updates_preserve_state_and_support_guarded_rollback(tmp_path: Path) -> None:
    original = document("durable")
    original["state"] = [{"id": "preference", "value": "concise"}]
    created = apply_profile(original, scope="project", project=tmp_path, config=Config())
    changed = document("durable")
    changed["state"] = []
    changed["metadata"]["description"] = "Changed"
    updated = apply_profile(
        changed,
        scope="project",
        project=tmp_path,
        config=Config(),
        expected_digest=created["profile"]["profile_digest"],
    )
    checkpoints = profile_checkpoints("durable", project=tmp_path, config=Config())
    restored = rollback_profile(
        "durable",
        checkpoints["checkpoints"][0]["path"],
        project=tmp_path,
        config=Config(),
        expected_digest=updated["profile"]["profile_digest"],
    )
    current = AgentProfileRegistry(tmp_path, Config()).get("durable")

    assert current is not None
    assert current.document["state"] == {"facts": [{"id": "preference", "text": "concise"}]}
    assert checkpoints["checkpoints"][0]["revision"] == 1
    assert restored["ok"] is True
    assert current.document["metadata"]["revision"] == 1

    detail = inspect_profile("durable", project=tmp_path, config=Config())
    assert detail["profile"]["name"] == "durable"
    assert detail["effective_profile"]["permission_mode"] == "balanced"
    assert len(detail["checkpoints"]) >= 1


def test_cli_preview_accepts_json_stdin(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_main.app,
        ["agent", "preview", "--project", str(tmp_path), "--input", "-"],
        input=json.dumps(document("stdin-profile")),
    )

    assert result.exit_code == 0, result.output
    assert '"contract": "magent.oap-profile.v1"' in result.output
    assert '"name": "stdin-profile"' in result.output


def test_profile_identity_reaches_research_recipes_and_graph_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    from magent import workbench_store as store_module
    from magent.agraph.execute import GraphExecutor
    from magent.recipes import run_recipe

    monkeypatch.setattr(store_module, "USERS_DIR", tmp_path / "users")
    profile = SimpleNamespace(
        provider="nous-portal", model="deepseek-v4-flash", tools={"read_file"}
    )
    graph = GraphExecutor(
        username="desktop-profile-test",
        config=Config(),
        project=tmp_path,
        store=WorkbenchStore("desktop-profile-test"),
        profile=profile,
    )
    recipe = run_recipe(
        WorkbenchStore("desktop-profile-test"),
        "docs-audit",
        tmp_path,
        agent="reviewer",
    )
    report = cli_main._write_research_report(
        {"topic": "Profile research", "summary": "Result", "sources": []},
        project=tmp_path,
    )

    assert graph.profile is profile
    assert recipe["plan"]["agent_profile"] == "reviewer"
    assert report.parent == tmp_path
