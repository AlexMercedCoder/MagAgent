"""S-2: `magent plan <sub>` with a default `create` and hidden plan-* aliases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent.cli import main as cli_main
from tests.unit.test_cli import redirect_config

runner = CliRunner()
SUBCOMMANDS = ["create", "list", "apply", "sandbox", "exec", "preview", "run", "show", "discard"]
ALIASES = ["list", "apply", "sandbox", "exec", "preview", "run", "show", "discard"]


@pytest.fixture
def project(monkeypatch, tmp_path: Path) -> Path:
    redirect_config(monkeypatch, tmp_path)
    assert runner.invoke(cli_main.app, ["user", "create", "alex"]).exit_code == 0
    folder = tmp_path / "project"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def test_plan_group_lists_every_subcommand() -> None:
    result = runner.invoke(cli_main.app, ["plan", "--help"])
    assert result.exit_code == 0
    for name in SUBCOMMANDS:
        assert name in result.output


@pytest.mark.parametrize("alias", ALIASES)
def test_legacy_aliases_are_hidden_but_work(alias: str) -> None:
    top = runner.invoke(cli_main.app, ["--help"])
    assert f"plan-{alias}" not in top.output
    result = runner.invoke(cli_main.app, [f"plan-{alias}", "--help"])
    assert result.exit_code == 0, result.output


def test_bare_goal_still_creates_a_plan_and_aliases_share_state(project: Path) -> None:
    created = runner.invoke(cli_main.app, ["plan", "Add a smoke test", "--save", "--json"])
    assert created.exit_code == 0, created.output
    options_first = runner.invoke(cli_main.app, ["plan", "--save", "Write docs"])
    assert options_first.exit_code == 0, options_first.output
    explicit = runner.invoke(cli_main.app, ["plan", "create", "Third", "--save"])
    assert explicit.exit_code == 0, explicit.output

    new = runner.invoke(cli_main.app, ["plan", "list"])
    old = runner.invoke(cli_main.app, ["plan-list"])
    assert new.exit_code == old.exit_code == 0
    assert new.output == old.output
    assert "Add a smoke test" in new.output and "Write docs" in new.output
    shown = runner.invoke(cli_main.app, ["plan", "show", "plan_0001"])
    assert json.loads(shown.output)["goal"] == "Add a smoke test"
    assert runner.invoke(cli_main.app, ["plan-show", "plan_0001"]).output == shown.output


def test_plan_without_arguments_shows_help() -> None:
    result = runner.invoke(cli_main.app, ["plan"])
    assert "Usage" in result.output and "create" in result.output
