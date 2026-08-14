from __future__ import annotations

from types import SimpleNamespace

import pytest

from magent.agent_runtime.lifecycle import LifecycleRuntimeMixin
from magent.daemon import _execute_item
from magent.daily_driver import create_goal
from magent.goal_orchestrator import create_orchestrated_goal
from magent.skills import SkillRegistry
from magent.subagents import SubAgentRunner
from magent.workbench import WorkbenchStore


def test_mcp_definitions_are_filtered_by_active_profile() -> None:
    runtime = LifecycleRuntimeMixin()
    runtime.config = SimpleNamespace(selective_tools=False)
    runtime.tools = SimpleNamespace(
        get_tool_definitions=lambda: [],
        get_tool_definitions_for_message=lambda _message: [],
    )
    runtime.mcp = SimpleNamespace(
        get_tool_definitions=lambda: [
            {"type": "function", "function": {"name": "mcp__github__issue"}},
            {"type": "function", "function": {"name": "mcp__shell__run"}},
        ]
    )
    runtime.profile = SimpleNamespace(mcp_servers=("github",))

    names = [item["function"]["name"] for item in runtime._tool_definitions("task")]
    assert names == ["mcp__github__issue"]
    assert runtime._mcp_tool_allowed("mcp__github__issue")
    assert not runtime._mcp_tool_allowed("mcp__shell__run")


def test_skill_context_can_be_restricted_by_profile(tmp_path) -> None:
    for name in ("review", "deploy"):
        path = tmp_path / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            f"---\nname: {name}\ndescription: {name} work\ntrigger_keywords: [{name}]\n---\n\nUse {name}.\n",
            encoding="utf-8",
        )
    registry = SkillRegistry(extra_dirs=[tmp_path])
    registry._search_dirs = [tmp_path]
    assert registry.load(respect_lockfile=False) == 2
    context = registry.build_skill_context("review deploy", allowed_names={"review"})
    assert "Skill: review" in context
    assert "Skill: deploy" not in context


@pytest.mark.asyncio
async def test_parent_profile_can_disable_subagents() -> None:
    parent = SimpleNamespace(
        max_subagents=1,
        max_parallel_subagents=1,
        max_delegation_depth=1,
        subagents=(),
    )
    runner = SubAgentRunner(
        "user",
        SimpleNamespace(),
        SimpleNamespace(),
        ".",
        SimpleNamespace(max_subagents=3, max_parallel_subagents=2),
        quiet=True,
        parent_profile=parent,
    )
    task = await runner.spawn("child", "work")
    assert task.done
    assert "does not permit" in task.error


def test_daemon_ask_propagates_agent_profile(monkeypatch) -> None:
    captured = {}

    def run(command, project, *, control_state=None):
        captured["command"] = command
        return {"ok": True}

    monkeypatch.setattr("magent.daemon._run_command", run)
    result = _execute_item(
        {
            "kind": "ask",
            "project": ".",
            "payload": {"task": "inspect", "agent": "review"},
        }
    )
    assert result["ok"]
    assert captured["command"][-2:] == ["--agent", "review"]


def test_goal_records_and_queues_agent_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("magent.workbench.USERS_DIR", tmp_path / "state")
    store = WorkbenchStore("oap-goal-test")
    result = create_goal(
        store,
        "review the project",
        project=tmp_path,
        background=True,
        agent_profile="review",
    )
    assert result["goal"]["agent_profile"] == "review"
    assert result["queued"]["payload"]["agent"] == "review"


def test_orchestrated_goal_persists_profile_in_cached_plan(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("magent.workbench.USERS_DIR", tmp_path / "state")
    store = WorkbenchStore("oap-orchestration-test")
    result = create_orchestrated_goal(
        store,
        "inspect the project",
        project=tmp_path,
        agent_profile="review",
    )
    assert result["goal"]["agent_profile"] == "review"
    assert result["orchestration"]["agent_profile"] == "review"
