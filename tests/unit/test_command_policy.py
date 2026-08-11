from __future__ import annotations

from types import SimpleNamespace

import pytest

import magent.command_policy as policy


def completed(returncode: int = 0):
    return SimpleNamespace(returncode=returncode, stdout="out", stderr="err")


def test_command_policy_blocks_destructive_commands_unless_explicitly_allowed() -> None:
    blocked = policy.command_policy("rm -rf /tmp/project")
    allowed = policy.command_policy("rm -rf /tmp/project", allow_block=True)

    assert blocked["blocked"] is True
    assert blocked["ok"] is False
    assert allowed["blocked"] is False
    assert allowed["ok"] is True


def test_policy_checked_shell_covers_block_success_failure_and_exception(
    tmp_path, monkeypatch
) -> None:
    assert policy.run_policy_checked_shell("rm -rf /tmp/project", cwd=tmp_path)["blocked"]

    monkeypatch.setattr(policy.subprocess, "run", lambda *args, **kwargs: completed())
    success = policy.run_policy_checked_shell("git status", cwd=tmp_path, env={"SAFE": "1"})
    assert success["ok"] is True
    assert success["stdout"] == "out"

    monkeypatch.setattr(policy.subprocess, "run", lambda *args, **kwargs: completed(2))
    assert policy.run_policy_checked_shell("git status", cwd=tmp_path)["ok"] is False

    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("late")),
    )
    assert "late" in policy.run_policy_checked_shell("git status", cwd=tmp_path)["error"]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python -V", {"argv": ["python", "-V"], "shell": True, "timeout": None}),
        (
            {"argv": ["python", "-V"], "timeout": 8},
            {"argv": ["python", "-V"], "shell": False, "timeout": 8},
        ),
        (
            {"command": "git status", "shell": False, "timeout": 9},
            {"argv": ["git", "status"], "shell": False, "timeout": 9},
        ),
        ({"command": "", "shell": True}, {"argv": [], "shell": True, "timeout": None}),
        (("git", "status"), {"argv": ["git", "status"], "shell": False, "timeout": None}),
    ],
)
def test_normalize_command_spec(command, expected) -> None:
    result = policy.normalize_command_spec(command)
    assert {key: result[key] for key in expected} == expected


def test_policy_checked_command_handles_argv_shell_block_and_exception(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return completed()

    monkeypatch.setattr(policy.subprocess, "run", fake_run)
    argv_result = policy.run_policy_checked_command(
        {"argv": ["python", "-V"], "timeout": 7}, cwd=tmp_path
    )
    shell_result = policy.run_policy_checked_command("git status", cwd=tmp_path)

    assert argv_result["ok"] is True
    assert argv_result["timeout"] == 7
    assert calls[0][0] == ["python", "-V"]
    assert calls[0][1]["shell"] is False
    assert shell_result["shell"] is True
    assert policy.run_policy_checked_command("rm -rf /tmp/project", cwd=tmp_path)["blocked"]

    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")),
    )
    failed = policy.run_policy_checked_command(["git", "status"], cwd=tmp_path)
    assert failed["ok"] is False
    assert "unavailable" in failed["error"]


def test_policy_checked_exec_uses_argv_without_shell(tmp_path, monkeypatch) -> None:
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs))
        return completed()

    monkeypatch.setattr(policy.subprocess, "run", fake_run)
    result = policy.run_policy_checked_exec("git status", cwd=tmp_path)

    assert result.returncode == 0
    assert seen[0][0] == ["git", "status"]
    assert seen[0][1] == {"cwd": str(tmp_path), "text": True}
