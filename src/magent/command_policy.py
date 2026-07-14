"""Shared shell command policy helpers."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from magent.permissions import RiskTier, classify_shell_command


def command_policy(command: str, *, allow_block: bool = False) -> dict[str, Any]:
    """Classify a command and return whether it may run in internal automation."""
    tier = classify_shell_command(command)
    blocked = tier >= RiskTier.BLOCK and not allow_block
    return {"ok": not blocked, "tier": int(tier), "blocked": blocked, "command": command}


def run_policy_checked_shell(
    command: str,
    *,
    cwd: str | Path,
    timeout: int = 60,
    allow_block: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run shell command only after shared command policy classification."""
    policy = command_policy(command, allow_block=allow_block)
    if not policy["ok"]:
        return {**policy, "error": "Blocked by MagAgent command policy"}
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            **policy,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as e:
        return {**policy, "ok": False, "error": str(e)}


def normalize_command_spec(command: str | Sequence[str] | Mapping[str, Any]) -> dict[str, Any]:
    """Normalize legacy shell strings and structured argv command specs."""
    if isinstance(command, str):
        return {
            "command": command,
            "argv": shlex.split(command),
            "shell": True,
            "timeout": None,
        }
    if isinstance(command, Mapping):
        timeout = command.get("timeout")
        if "argv" in command:
            argv = [str(item) for item in command.get("argv") or []]
            return {
                "command": shlex.join(argv),
                "argv": argv,
                "shell": False,
                "timeout": int(timeout) if timeout is not None else None,
            }
        raw_command = str(command.get("command") or "")
        use_shell = bool(command.get("shell", True))
        return {
            "command": raw_command,
            "argv": shlex.split(raw_command) if raw_command else [],
            "shell": use_shell,
            "timeout": int(timeout) if timeout is not None else None,
        }
    argv = [str(item) for item in command]
    return {
        "command": shlex.join(argv),
        "argv": argv,
        "shell": False,
        "timeout": None,
    }


def run_policy_checked_command(
    command: str | Sequence[str] | Mapping[str, Any],
    *,
    cwd: str | Path,
    timeout: int = 60,
    allow_block: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a command spec after shared policy classification.

    String commands preserve legacy shell behavior. List/tuple or ``{"argv": [...]}``
    commands run without a shell and are preferred for evals and automated checks.
    """
    spec = normalize_command_spec(command)
    effective_timeout = int(spec.get("timeout") or timeout)
    policy = command_policy(spec["command"], allow_block=allow_block)
    base = {
        **policy,
        "argv": spec["argv"],
        "shell": spec["shell"],
        "timeout": effective_timeout,
    }
    if not policy["ok"]:
        return {**base, "error": "Blocked by MagAgent command policy"}
    try:
        result = subprocess.run(
            spec["command"] if spec["shell"] else spec["argv"],
            cwd=str(cwd),
            shell=bool(spec["shell"]),
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            env=env,
        )
        return {
            **base,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as e:
        return {**base, "ok": False, "error": str(e)}


def run_policy_checked_exec(command: str, *, cwd: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a simple command without shell expansion."""
    argv = shlex.split(command)
    return subprocess.run(argv, cwd=str(cwd), text=True)
