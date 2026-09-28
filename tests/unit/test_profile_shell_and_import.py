"""I-17: OAP `permissions.shell: ask` asks for every shell command.
I-18: `magent agent import` keeps the profile's revision, history, state and digest.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from magent.agent_profiles.digest import digest_document, digest_spec
from magent.agent_profiles.documents import parse_document
from magent.agent_profiles.effective import resolve_effective_profile
from magent.agent_profiles.models import ResolvedProfile
from magent.tools.executor import ToolExecutor


class Config:
    permission_mode = "balanced"
    default_provider = "mock"
    default_model = "offline-demo"
    memory_budget_tokens = 4000
    max_subagents = 3
    max_parallel_subagents = 2
    mcp_servers: dict = {}

    def __init__(self, values: dict | None = None) -> None:
        self.values = values or {}

    def get(self, *parts, default=None):
        return self.values.get(parts, default)


def profile(shell: str | None = None, **permissions) -> ResolvedProfile:
    if shell is not None:
        permissions["shell"] = shell
    document = {
        "oap": "1.0",
        "kind": "AgentProfile",
        "metadata": {"name": "careful", "description": "Asks first.", "revision": 1},
        "spec": {"role": {"instructions": "Be careful."}, "permissions": permissions},
    }
    return ResolvedProfile(
        document=document,
        source_path=None,
        trust="user",
        spec_digest=digest_spec(document),
        profile_digest=digest_document(document),
    )


GRANTED = frozenset({"run_shell", "run_python", "install_package", "git_op", "read_file"})


# ------------------------------------------------------------------- I-17


def test_effective_profile_carries_the_shell_decision() -> None:
    assert resolve_effective_profile(profile("ask"), Config(), GRANTED).shell == "ask"
    assert resolve_effective_profile(profile(), Config(), GRANTED).shell == "allow"
    denied = resolve_effective_profile(profile("deny"), Config(), GRANTED)
    assert denied.shell == "deny"
    assert not denied.tools & {"run_shell", "run_python", "install_package", "git_op"}
    assert "read_file" in denied.tools
    # A harness that turned the read-only auto-allow off narrows `allow` to `ask`.
    strict = Config({("permissions", "read_only_shell_auto_allow"): False})
    narrowed = resolve_effective_profile(profile("allow"), strict, GRANTED)
    assert narrowed.shell == "ask"
    assert any(item.field == "permissions.shell" for item in narrowed.adjustments)
    assert narrowed.as_dict()["shell"] == "ask"


def _tools(tmp_path: Path, *, mode: str = "balanced", prompt=None, config=None) -> ToolExecutor:
    return ToolExecutor(
        str(tmp_path),
        permission_mode=mode,
        username="i17",
        interactive_permissions=False,
        permission_prompt=prompt,
        config=config,
        session_id="i17-session",
    )


def test_echo_needs_approval_under_shell_ask(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    tools.profile_shell = "ask"
    result = asyncio.run(tools.run_shell("echo hello"))
    assert result["ok"] is False and result.get("permission_required") is True


@pytest.mark.parametrize("command", ["echo hi", "cat README.md", "grep -r x .", "sed -n 1p f"])
@pytest.mark.parametrize("mode", ["balanced", "silent", "yolo"])
def test_every_read_only_command_is_asked_under_shell_ask(
    tmp_path: Path, command: str, mode: str
) -> None:
    asked: list[str] = []

    def prompt(description, _tier, _action=None):
        asked.append(description)
        return "deny"

    tools = _tools(tmp_path, mode=mode, prompt=prompt)
    tools.profile_shell = "ask"
    result = asyncio.run(tools.run_shell(command))
    assert result["ok"] is False
    assert asked and command in asked[0]


def test_approved_echo_runs_under_shell_ask(tmp_path: Path) -> None:
    asked: list[str] = []

    def prompt(description, _tier, _action=None):
        asked.append(description)
        return "once"

    tools = _tools(tmp_path, prompt=prompt)
    tools.profile_shell = "ask"
    result = asyncio.run(tools.run_shell("echo approved"))
    assert result["ok"] is True and "approved" in result["stdout"]
    assert len(asked) == 1


def test_default_mode_still_auto_runs_read_only_commands(tmp_path: Path) -> None:
    def prompt(*_args):
        raise AssertionError("a read-only command should not ask in the default mode")

    result = asyncio.run(_tools(tmp_path, prompt=prompt).run_shell("echo fine"))
    assert result["ok"] is True


def test_config_can_turn_the_read_only_auto_allow_off(tmp_path: Path) -> None:
    config = Config({("permissions", "read_only_shell_auto_allow"): False})
    result = asyncio.run(_tools(tmp_path, config=config).run_shell("echo hi"))
    assert result.get("permission_required") is True


def test_run_python_is_asked_under_shell_ask_even_in_silent_mode(tmp_path: Path) -> None:
    tools = _tools(tmp_path, mode="silent")
    tools.profile_shell = "ask"
    result = asyncio.run(tools.run_python("print(1)"))
    assert result.get("permission_required") is True


# ------------------------------------------------------------------- I-18


def _source_profile(tmp_path: Path) -> Path:
    document = {
        "oap": "1.0",
        "kind": "AgentProfile",
        "metadata": {
            "name": "reviewer",
            "description": "Reviews pull requests for correctness.",
            "revision": 7,
            "annotations": {"loro.io/tier": "advanced"},
        },
        "spec": {"role": {"instructions": "Review carefully."}},
        "state": {"facts": [{"id": "f1", "text": "Team prefers small PRs."}]},
        "history": [
            {"revision": 7, "at": "2026-09-01T00:00:00Z", "by": "loro", "sections": ["state"]}
        ],
    }
    path = tmp_path / "src" / "reviewer.agent.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_import_keeps_revision_history_state_and_digest(tmp_path: Path) -> None:
    from magent.agent_profiles.desktop import import_profile

    source = _source_profile(tmp_path)
    original, _body, _encoding = parse_document(source)
    project = tmp_path / "project"
    project.mkdir()
    result = import_profile(source, scope="portable", project=project, config=Config())
    assert result["ok"], result
    imported, _body, _encoding = parse_document(Path(result["path"]))
    assert Path(result["path"]).parent == project / ".agents"
    assert imported["metadata"]["revision"] == 7
    assert imported["history"] == original["history"]
    assert imported["state"] == original["state"]
    assert imported["metadata"]["annotations"] == {"loro.io/tier": "advanced"}
    assert digest_document(imported) == digest_document(original)
    assert result["digest_preserved"] is True
    provenance = json.loads(
        (project / ".magent" / "profile-imports" / "reviewer.json").read_text(encoding="utf-8")
    )
    assert provenance["source_profile_digest"] == digest_document(original)
    assert provenance["revision"] == 7 and provenance["trust_at_source"] == "imported"


def test_import_with_a_new_name_keeps_the_revision_and_says_the_digest_changed(
    tmp_path: Path,
) -> None:
    from magent.agent_profiles.desktop import import_profile

    source = _source_profile(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    result = import_profile(
        source, scope="project", project=project, config=Config(), name="reviewer2"
    )
    assert result["ok"], result
    imported, _body, _encoding = parse_document(Path(result["path"]))
    assert imported["metadata"]["revision"] == 7
    assert result["digest_preserved"] is False
    assert result["provenance"]["renamed_from"] == "reviewer"


def test_import_refuses_to_overwrite_an_existing_profile(tmp_path: Path) -> None:
    from magent.agent_profiles.desktop import import_profile

    source = _source_profile(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    assert import_profile(source, scope="project", project=project, config=Config())["ok"]
    again = import_profile(source, scope="project", project=project, config=Config())
    assert again["ok"] is False and again.get("conflict") is True


def test_shared_agents_directory_is_discovered_and_native_wins(tmp_path: Path) -> None:
    from magent.agent_profiles.registry import AgentProfileRegistry

    source = _source_profile(tmp_path)
    project = tmp_path / "project"
    (project / ".agents").mkdir(parents=True)
    (project / ".agents" / "reviewer.agent.yaml").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    registry = AgentProfileRegistry(project, Config())
    found = registry.get("reviewer")
    assert found is not None and found.source_path.parent == (project / ".agents").resolve()

    native = project / ".magent" / "agents"
    native.mkdir(parents=True)
    (native / "reviewer.agent.yaml").write_text(
        source.read_text(encoding="utf-8").replace("revision: 7", "revision: 8"),
        encoding="utf-8",
    )
    profiles, warnings = registry.discover()
    assert profiles["reviewer"].source_path.parent == native.resolve()
    assert any("reviewer" in warning for warning in warnings)
