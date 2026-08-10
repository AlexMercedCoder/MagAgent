"""Project hook loading and execution."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from magent.command_policy import run_policy_checked_shell

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


_HOOK_CACHE: dict[str, tuple[float, int, dict[str, list[str]]]] = {}


def load_hooks(project: str | Path = ".") -> dict[str, list[str]]:
    """Load and parse .magent/hooks.toml, cached on the file's mtime and size.

    This was re-read and re-parsed twice per tool call (pre and post), for
    every tool call of every turn.
    """
    path = hook_config_path(project)
    if not path.exists():
        _HOOK_CACHE.pop(str(path), None)
        return {}

    try:
        stat = path.stat()
        signature = (stat.st_mtime, stat.st_size)
    except OSError:
        signature = (0.0, 0)

    cached = _HOOK_CACHE.get(str(path))
    if cached and (cached[0], cached[1]) == signature:
        return dict(cached[2])

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
    _HOOK_CACHE[str(path)] = (signature[0], signature[1], dict(hooks))
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
        result = run_policy_checked_shell(command, cwd=root, timeout=timeout, env=env)
        results.append(
            {
                "event": event,
                "command": command,
                "ok": result.get("ok", False),
                "tier": result.get("tier"),
                "returncode": result.get("returncode"),
                "stdout": str(result.get("stdout", ""))[-4000:],
                "stderr": str(result.get("stderr", ""))[-4000:],
                "error": result.get("error", ""),
            }
        )
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


async def run_hooks_async(
    project: str | Path,
    event: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Run hooks off the event loop.

    Hook subprocesses ran synchronously inside the async loop, blocking every
    other task for up to `timeout` seconds per hook.
    """
    import asyncio

    return await asyncio.to_thread(run_hooks, project, event, payload, timeout=timeout)
