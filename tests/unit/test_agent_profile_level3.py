from __future__ import annotations

from pathlib import Path

import pytest

from magent.agent_profiles.effective import resolve_effective_profile
from magent.agent_profiles.errors import ProfileError
from magent.agent_profiles.registry import AgentProfileRegistry


class Config:
    permission_mode = "balanced"
    default_provider = "nous-portal"
    default_model = "deepseek-v4-flash"
    memory_budget_tokens = 4000
    memory_mode = "read_write"
    max_subagents = 4
    max_parallel_subagents = 3

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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_extends_preserves_parent_as_security_constraint(tmp_path: Path) -> None:
    root = tmp_path / ".magent" / "agents"
    _write(
        root / "base.yaml",
        """oap: '1.0'
metadata: {name: base, revision: 1}
spec:
  role: {instructions: Base}
  tools:
    allow: [read_file, run_shell]
    mcp_servers: [github, filesystem]
    skills: [review, docs]
  runtime:
    subagents: {allow: [review, docs], max_subagents: 2, max_parallel: 1, max_depth: 2}
  memory:
    stores:
      - {name: user-graph, kind: maggraph, mode: read}
""",
    )
    _write(
        root / "child.yaml",
        """oap: '1.0'
extends: base
metadata: {name: child, revision: 1}
spec:
  role: {instructions: Child}
  tools:
    allow: [read_file, write_file]
    mcp_servers: [github]
    skills: [docs]
  runtime:
    subagents: {allow: [docs], max_subagents: 4}
""",
    )
    profile = AgentProfileRegistry(tmp_path, Config()).get("child")
    assert profile is not None
    assert [item["metadata"]["name"] for item in profile.lineage] == ["base"]
    effective = resolve_effective_profile(
        profile, Config(), {"read_file", "write_file", "run_shell"}
    )
    assert effective.tools == {"read_file"}
    assert effective.mcp_servers == ("github",)
    assert effective.skills == ("docs",)
    assert effective.subagents == ("docs",)
    assert effective.max_subagents == 2
    assert effective.max_parallel_subagents == 1
    assert effective.max_delegation_depth == 2
    assert effective.allows_memory("read")
    assert not effective.allows_memory("write")


def test_extends_rejects_cycles_and_missing_parents(tmp_path: Path) -> None:
    root = tmp_path / ".magent" / "agents"
    _write(
        root / "a.yaml",
        "oap: '1.0'\nextends: b\nmetadata: {name: a, revision: 1}\nspec: {role: {instructions: A}}\n",
    )
    _write(
        root / "b.yaml",
        "oap: '1.0'\nextends: a\nmetadata: {name: b, revision: 1}\nspec: {role: {instructions: B}}\n",
    )
    with pytest.raises(ProfileError, match="inheritance cycle"):
        AgentProfileRegistry(tmp_path, Config()).discover()
    (root / "b.yaml").unlink()
    with pytest.raises(ProfileError, match="extended profile not found"):
        AgentProfileRegistry(tmp_path, Config()).discover()


def test_child_effective_profile_cannot_widen_parent(tmp_path: Path) -> None:
    root = tmp_path / ".magent" / "agents"
    _write(
        root / "parent.yaml",
        """oap: '1.0'
metadata: {name: parent, revision: 1}
spec:
  role: {instructions: Parent}
  tools: {allow: [read_file], mcp_servers: [github], skills: [review]}
  permissions: {default: paranoid}
  runtime: {subagents: {allow: [child], max_subagents: 1, max_parallel: 1, max_depth: 1}}
  memory: {stores: [{name: user-graph, kind: maggraph, mode: read}]}
""",
    )
    _write(
        root / "child.yaml",
        """oap: '1.0'
metadata: {name: child, revision: 1}
spec:
  role: {instructions: Child}
  tools: {allow: ['*'], mcp_servers: [github, shell], skills: [review, deploy]}
  permissions: {default: yolo}
""",
    )
    registry = AgentProfileRegistry(tmp_path, Config())
    parent = resolve_effective_profile(
        registry.get("parent"), Config(), {"read_file", "write_file"}
    )  # type: ignore[arg-type]
    child = resolve_effective_profile(
        registry.get("child"),
        Config(),
        {"read_file", "write_file"},
        parent=parent,  # type: ignore[arg-type]
    )
    assert child.tools == {"read_file"}
    assert child.permission_mode == "paranoid"
    assert child.mcp_servers == ("github",)
    assert child.skills == ("review",)
    assert child.max_delegation_depth == 0
    assert child.allows_memory("read")
    assert not child.allows_memory("write")
