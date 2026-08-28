from __future__ import annotations

from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from magent import config as magent_config
from magent.agent_profiles.authoring import (
    build_profile_document,
    clear_default_profile,
    default_profile_status,
    set_default_profile,
    write_profile,
)
from magent.agent_profiles.documents import parse_document
from magent.agent_profiles.registry import AgentProfileRegistry
from magent.cli import main as cli_main
from magent.cli import profile_wizard
from magent.config import Config


def _redirect_config(monkeypatch, root: Path) -> None:
    config_dir = root / "config"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", config_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", config_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", config_dir / "users" / "current")


def test_build_and_write_complete_profile(tmp_path: Path) -> None:
    document = build_profile_document(
        name=" Pair Programmer ",
        description="Collaborative coding profile",
        annotations={"owner": "alex"},
        role={
            "instructions": "Work alongside the user.",
            "persona": "Patient and direct",
            "objectives": ["Make progress"],
            "constraints": ["Verify edits"],
        },
        model={"provider": "openrouter", "id": "deepseek/deepseek-chat"},
        tools={"allow": ["read", "write"], "deny": ["delete"], "skills": ["testing"]},
        permissions={"default": "balanced"},
        runtime={
            "mode": "primary",
            "max_turns": 8,
            "subagents": {"max_subagents": 2, "max_parallel": 1, "max_depth": 2},
        },
        memory={"mode": "read_write"},
        context={"budget": {"max_state_tokens": 600}},
        lifecycle={"writeback": "propose", "on_start": "profile-start"},
        extends=["magagent"],
    )

    result = write_profile(document, scope="project", project=tmp_path)

    assert result["ok"] is True
    parsed, _body, _encoding = parse_document(Path(result["path"]))
    assert parsed["metadata"]["name"] == "pair-programmer"
    assert parsed["metadata"]["annotations"] == {"owner": "alex"}
    assert parsed["spec"]["model"]["provider"] == "openrouter"
    assert parsed["kind"] == "AgentProfile"
    assert parsed["spec"]["lifecycle"]["on_start"] == [{"hook": "profile-start"}]


def test_default_profile_persists_and_can_be_cleared(monkeypatch, tmp_path: Path) -> None:
    _redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alex")
    document = build_profile_document(
        name="docs-helper",
        description="Docs",
        role={"instructions": "Write documentation."},
    )
    assert write_profile(document, scope="project", project=tmp_path)["ok"]

    result = set_default_profile("docs-helper", username="alex", project=tmp_path)

    assert result == {"ok": True, "profile": "docs-helper", "scope": "user"}
    assert magent_config.load_config("alex").default_agent_profile == "docs-helper"
    assert default_profile_status("alex", tmp_path)["resolved"]["name"] == "docs-helper"
    assert clear_default_profile(username="alex")["ok"] is True
    assert magent_config.load_config("alex").default_agent_profile == "magagent"


def test_magagent_builtin_has_general_personality(tmp_path: Path) -> None:
    profile = AgentProfileRegistry(tmp_path).get("magagent")

    assert profile is not None
    role = profile.document["spec"]["role"]
    assert "MagAgent" in role["persona"]["tone"]
    assert role["objectives"]


def test_cli_profile_resolution_uses_default_and_supports_opt_out(tmp_path: Path) -> None:
    config = Config(
        {
            "defaults": {
                "provider": "ollama",
                "model": "local",
                "permission_mode": "balanced",
            },
            "agent_profiles": {"default_profile": "magagent"},
            "agent": {"max_model_rounds_per_turn": 16},
        }
    )

    effective = cli_main._resolve_cli_profile(None, str(tmp_path), config)

    assert effective is not None
    assert effective.name == "magagent"
    assert cli_main._resolve_cli_profile("none", str(tmp_path), config) is None


def test_profile_default_commands(monkeypatch, tmp_path: Path) -> None:
    _redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alex")
    magent_config.set_current_user("alex")
    runner = CliRunner()

    status = runner.invoke(cli_main.app, ["profile", "default", "--project", str(tmp_path)])
    selected = runner.invoke(
        cli_main.app,
        ["profile", "set-default", "review", "--project", str(tmp_path)],
    )
    selected_name = magent_config.load_config("alex").default_agent_profile
    cleared = runner.invoke(cli_main.app, ["profile", "clear-default"])

    assert status.exit_code == 0
    assert '"profile": "magagent"' in status.output
    assert selected.exit_code == 0
    assert selected_name == "review"
    assert magent_config.load_config("alex").default_agent_profile == "magagent"
    assert cleared.exit_code == 0


def test_profile_wizard_writes_valid_project_profile(monkeypatch, tmp_path: Path) -> None:
    answers = {
        "Profile name": "builder",
        "Short description": "Builds polished features",
        "Metadata annotations (key=value, comma-separated, optional)": "team=product",
        "Save scope (user/project/portable)": "project",
        "Profiles to extend (comma-separated, blank for none)": "magagent",
        "Core instructions": "Build requested features and verify them.",
        "Persona and communication style": "Focused and friendly",
        "Objectives (comma-separated)": "Implement,Test",
        "Profile constraints (comma-separated)": "Verify results",
        "Example behaviors (comma-separated, optional)": "Summarize changed files",
        "Tool policy (all/coding/read-only/custom)": "coding",
        "Requested permission mode": "balanced",
        "Network access": "read",
        "Memory access": "read_write",
        "Runtime role": "primary",
        "Allowed subagent profiles (comma-separated, blank for any)": "review",
        "Profile state writeback": "propose",
    }
    confirmations = {
        "Choose a dedicated provider and model for this profile?": False,
        "Allow this profile to delegate to subagents?": True,
        "Configure named lifecycle hooks?": False,
        "Write this profile?": True,
        "Make this the default profile?": False,
    }
    integers = {
        "Maximum model rounds per user turn": 10,
        "Maximum subagents": 2,
        "Maximum parallel subagents": 1,
        "Maximum delegation depth": 2,
        "Maximum profile-state context tokens": 500,
    }
    monkeypatch.setattr(profile_wizard.Prompt, "ask", lambda label, **_kwargs: answers[label])
    monkeypatch.setattr(
        profile_wizard.Confirm, "ask", lambda label, **_kwargs: confirmations[label]
    )
    monkeypatch.setattr(profile_wizard.IntPrompt, "ask", lambda label, **_kwargs: integers[label])
    monkeypatch.setattr(profile_wizard, "_available_skills", lambda: [])
    config = Config(
        {
            "defaults": {
                "provider": "ollama",
                "model": "local",
                "permission_mode": "balanced",
            },
            "agent": {"max_model_rounds_per_turn": 16},
            "agent_profiles": {
                "default_profile": "magagent",
                "max_state_tokens": 1200,
                "max_delegation_depth": 3,
            },
            "subagents": {"max_subagents": 3, "max_parallel_subagents": 2},
            "mcp": {},
        }
    )

    output = Console(record=True, width=100, color_system=None)
    result = profile_wizard.run_profile_wizard(
        username="alex", config=config, store=object(), project=tmp_path, console=output
    )

    assert result["ok"] is True
    profile = AgentProfileRegistry(tmp_path).get("builder")
    assert profile is not None
    assert profile.document["metadata"]["annotations"] == {"team": "product"}
    assert profile.document["spec"]["runtime"]["subagents"]["allow"] == ["review"]
    assert profile.document["spec"]["permissions"]["network"] == "allow"
    rendered = output.export_text()
    assert "Where should this profile live?" in rendered
    assert "Permission modes" in rendered
    assert "Web search needs both network access" in rendered
    assert "Profile state writeback" in rendered
    assert "cannot make it more permissive" in rendered
