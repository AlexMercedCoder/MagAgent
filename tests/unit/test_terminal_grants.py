"""G-12: terminal "always" approvals become expiring, receipted, revocable grants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent.cli import main as cli_main
from magent.permissions import RiskTier
from magent.tools import shell as shell_module
from magent.tools.executor import ToolExecutor
from magent.workbench_store import WorkbenchStore
from tests.unit.test_cli import redirect_config

COMMAND = "npm run lint"


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    redirect_config(monkeypatch, tmp_path)
    assert CliRunner().invoke(cli_main.app, ["user", "create", "alex"]).exit_code == 0
    project = tmp_path / "project"
    project.mkdir()
    return project


def _executor(project: Path, session: str = "s1") -> ToolExecutor:
    return ToolExecutor(
        str(project), permission_mode="balanced", username="alex", session_id=session
    )


def _answer(monkeypatch, answer: str) -> list[str]:
    asked: list[str] = []

    def ask(*_args, **_kwargs):
        asked.append(answer)
        return answer

    monkeypatch.setattr(shell_module.Prompt, "ask", ask)
    return asked


def _state(project: Path) -> dict:
    root = WorkbenchStore("alex").root
    return json.loads((root / "aais-approvals.json").read_text())


def test_always_creates_an_expiring_grant_and_later_hits_are_receipted(home, monkeypatch) -> None:
    asked = _answer(monkeypatch, "always")
    first = _executor(home)._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    assert first.approved and first.reason == "user-persistent-allow"
    assert asked == ["always"]

    state = _state(home)
    [grant] = state["extensions"]["grants"]
    assert grant["scope"] == "persistent" and grant["expires_at"]
    assert grant["source"] == "magent-terminal"
    assert grant["action_summary"] == f"Run: {COMMAND}"
    # The terminal answer itself is in the approval log with a human actor.
    decisions = [item["decision"]["actor"] for item in state["decisions"].values()]
    assert any(actor["authenticated_by"] == "magent-terminal" for actor in decisions)

    # A later session: no prompt, and the use is receipted.
    asked.clear()
    second = _executor(home, session="s2")._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    assert second.approved and second.reason == "grant-persistent"
    assert asked == []
    state = _state(home)
    [hit] = state["extensions"]["grant_hits"]
    assert hit["session_id"] == "s2"
    receipt = state["resolutions"][hit["request_id"]]
    assert receipt["resolution"]["outcome"] == "approved"
    # No trusted pattern was written to the profile.
    from magent.permission_ux import permission_trust_list

    assert permission_trust_list("alex")["trusted_shell_patterns"] == []


def test_grant_is_listed_and_revocable_from_the_cli(home, monkeypatch) -> None:
    _answer(monkeypatch, "always")
    _executor(home)._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    runner = CliRunner()
    listed = json.loads(
        runner.invoke(cli_main.app, ["permission", "grants", "list", "--json"]).output
    )
    [row] = listed["grants"]
    assert row["source"] == "magent-terminal" and row["status"] == "active"
    revoked = runner.invoke(cli_main.app, ["permission", "grants", "revoke", row["id"]])
    assert revoked.exit_code == 0, revoked.output

    asked = _answer(monkeypatch, "no")
    result = _executor(home, "s3")._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    assert not result.approved and asked == ["no"]
    denied = max(_state(home)["resolutions"].values(), key=lambda item: item["sequence"])
    assert denied["resolution"]["outcome"] == "denied"


def test_grants_are_exact_to_the_project(home, monkeypatch, tmp_path: Path) -> None:
    _answer(monkeypatch, "always")
    _executor(home)._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    other = tmp_path / "other"
    other.mkdir()
    asked = _answer(monkeypatch, "once")
    result = _executor(other)._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    assert result.reason == "user-confirmed" and asked == ["once"]


def test_legacy_trusted_patterns_are_grandfathered_listed_and_revocable(home) -> None:
    from magent.config import load_user_profile, save_user_profile

    profile = load_user_profile("alex")
    profile.setdefault("permissions", {})["trusted_shell_patterns"] = [COMMAND]
    save_user_profile("alex", profile)
    executor = ToolExecutor(
        str(home), username="alex", trusted_shell_patterns=[COMMAND], session_id="s1"
    )
    assert executor._check_shell_permission(COMMAND, RiskTier.CONFIRM).reason == "trusted-shell"

    runner = CliRunner()
    listed = json.loads(
        runner.invoke(cli_main.app, ["permission", "grants", "list", "--json"]).output
    )
    [row] = listed["grants"]
    assert row["legacy"] is True and row["source"] == "profile-trusted-pattern"
    assert "never expires" in row["flag"]
    revoked = runner.invoke(cli_main.app, ["permission", "grants", "revoke", row["id"], "--json"])
    assert json.loads(revoked.output)["revoked"] == [row["id"]]
    assert load_user_profile("alex")["permissions"]["trusted_shell_patterns"] == []


def test_broker_ask_path_always_also_becomes_a_grant(home) -> None:
    executor = ToolExecutor(
        str(home),
        permission_mode="balanced",
        username="alex",
        session_id="gw",
        interactive_permissions=False,
        permission_prompt=lambda *_args, **_kwargs: "always",
    )
    first = executor._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    assert first.approved and first.reason == "user-persistent-allow"
    again = ToolExecutor(
        str(home),
        permission_mode="balanced",
        username="alex",
        session_id="gw2",
        interactive_permissions=False,
        permission_prompt=lambda *_args, **_kwargs: pytest.fail("grant should apply"),
    )
    assert again._check_shell_permission(COMMAND, RiskTier.CONFIRM).reason == "grant-persistent"


def test_unavailable_store_never_grants_and_falls_back_to_session(home, monkeypatch) -> None:
    root = WorkbenchStore("alex").root
    (root / "aais-approvals.json").write_text("{broken")
    _answer(monkeypatch, "always")
    executor = _executor(home)
    result = executor._check_shell_permission(COMMAND, RiskTier.CONFIRM)
    assert result.approved
    assert COMMAND in executor.session_shell_patterns
