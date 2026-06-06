"""Project hook loading and execution."""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

HOOK_EVENTS = {
    "pre_tool",
    "post_tool",
    "post_edit",
    "command_failure",
    "memory_candidate",
    "release_check",
}


def hook_config_path(project: str | Path = ".") -> Path:
    return Path(project).resolve() / ".magent" / "hooks.toml"


def load_hooks(project: str | Path = ".") -> dict[str, list[str]]:
    path = hook_config_path(project)
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}
    hooks: dict[str, list[str]] = {}
    raw = data.get("hooks", data)
    if not isinstance(raw, dict):
        return {}
    for event in HOOK_EVENTS:
        value = raw.get(event)
        if isinstance(value, dict):
            value = value.get("commands", [])
        if isinstance(value, str):
            hooks[event] = [value]
        elif isinstance(value, list):
            hooks[event] = [str(item) for item in value if str(item).strip()]
    return hooks


def run_hooks(
    project: str | Path,
    event: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Run configured shell hooks for an event."""
    if event not in HOOK_EVENTS:
        return []
    root = Path(project).resolve()
    payload = payload or {}
    results = []
    env = {
        **os.environ,
        "MAGENT_HOOK_EVENT": event,
        "MAGENT_HOOK_PAYLOAD": json.dumps(payload, default=str),
    }
    for command in load_hooks(root).get(event, []):
        try:
            result = subprocess.run(
                command,
                cwd=root,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            results.append(
                {
                    "event": event,
                    "command": command,
                    "ok": result.returncode == 0,
                    "returncode": result.returncode,
                    "stdout": result.stdout[-4000:],
                    "stderr": result.stderr[-4000:],
                }
            )
        except Exception as e:
            results.append({"event": event, "command": command, "ok": False, "error": str(e)})
    return results


def init_hooks(project: str | Path = ".", *, force: bool = False) -> dict[str, Any]:
    path = hook_config_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return {"ok": False, "error": f"Hooks file already exists: {path}", "path": str(path)}
    path.write_text(
        """[hooks]
# commands receive MAGENT_HOOK_EVENT and MAGENT_HOOK_PAYLOAD
pre_tool = []
post_tool = []
post_edit = []
command_failure = []
memory_candidate = []
release_check = []
""",
        encoding="utf-8",
    )
    return {"ok": True, "path": str(path)}
