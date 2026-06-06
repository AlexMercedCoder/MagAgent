"""GitHub PR and issue workflow helpers backed by the gh CLI."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any


def github_status(root: str | Path = ".") -> dict[str, Any]:
    """Report whether GitHub CLI is available and authenticated."""
    version = _run(root, ["gh", "--version"])
    auth = _run(root, ["gh", "auth", "status"])
    return {"ok": version["ok"] and auth["ok"], "gh_version": version, "auth": auth}


def list_issues(root: str | Path = ".", limit: int = 20, state: str = "open") -> dict[str, Any]:
    cmd = ["gh", "issue", "list", "--state", state, "--limit", str(limit), "--json", "number,title,state,author,labels,url"]
    return _json_command(root, cmd, "issues")


def list_prs(root: str | Path = ".", limit: int = 20, state: str = "open") -> dict[str, Any]:
    cmd = ["gh", "pr", "list", "--state", state, "--limit", str(limit), "--json", "number,title,state,author,headRefName,baseRefName,url"]
    return _json_command(root, cmd, "prs")


def show_issue(root: str | Path, number: int) -> dict[str, Any]:
    cmd = ["gh", "issue", "view", str(number), "--json", "number,title,state,author,body,labels,comments,url"]
    return _json_command(root, cmd, "issue")


def show_pr(root: str | Path, number: int) -> dict[str, Any]:
    cmd = ["gh", "pr", "view", str(number), "--json", "number,title,state,author,body,files,commits,reviewDecision,statusCheckRollup,url"]
    return _json_command(root, cmd, "pr")


def pr_checks(root: str | Path, number: int | None = None) -> dict[str, Any]:
    cmd = ["gh", "pr", "checks"]
    if number is not None:
        cmd.append(str(number))
    result = _run(root, cmd)
    return {"ok": result["ok"], "checks": result}


def _json_command(root: str | Path, cmd: list[str], key: str) -> dict[str, Any]:
    result = _run(root, cmd)
    if not result["ok"]:
        return {"ok": False, "error": result.get("stderr") or result.get("error", ""), "command": result}
    try:
        return {"ok": True, key: json.loads(result.get("stdout", "") or "null")}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": str(e), "command": result}


def _run(root: str | Path, cmd: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(cmd, cwd=Path(root).resolve(), text=True, capture_output=True, timeout=90)
        return {
            "ok": result.returncode == 0,
            "command": shlex.join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout[-6000:],
            "stderr": result.stderr[-6000:],
        }
    except Exception as e:
        return {"ok": False, "command": shlex.join(cmd), "error": str(e)}
