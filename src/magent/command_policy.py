"""Shared shell command policy helpers."""

from __future__ import annotations

import shlex
import subprocess
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


def run_policy_checked_exec(command: str, *, cwd: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a simple command without shell expansion."""
    argv = shlex.split(command)
    return subprocess.run(argv, cwd=str(cwd), text=True)
