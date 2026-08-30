"""Reviewed lifecycle operations for extensions in the local Web UI."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from magent.config import load_global_config, save_global_config

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _name(value: Any) -> str:
    name = str(value or "").strip()
    if not SAFE_NAME.fullmatch(name):
        raise ValueError("Names may contain letters, numbers, dots, underscores, and dashes.")
    return name


def manage_plugin(payload: dict[str, Any]) -> dict[str, Any]:
    from magent.plugins import install_plugin, uninstall_plugin

    action = str(payload.get("action") or "install")
    if action == "install":
        return install_plugin(str(payload.get("source") or ""), name=str(payload.get("name") or ""))
    if action == "delete":
        return uninstall_plugin(_name(payload.get("name")))
    return {"ok": False, "error": "Unknown plugin action."}


def manage_skill(project: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(project).resolve() / ".magent" / "skills"
    name = _name(payload.get("name"))
    target = (root / name / "SKILL.md").resolve(strict=False)
    target.relative_to(root.resolve(strict=False))
    action = str(payload.get("action") or "save")
    if action == "delete":
        if not target.is_file():
            return {"ok": False, "error": f"Project skill not found: {name}"}
        shutil.rmtree(target.parent)
        return {"ok": True, "name": name, "removed": True}
    description = str(payload.get("description") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not description or not body:
        return {"ok": False, "error": "A skill description and instructions are required."}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\n"
        f"name: {json.dumps(name)}\n"
        f"description: {json.dumps(description)}\n"
        "version: \"1.0\"\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return {"ok": True, "name": name, "path": str(target)}


def manage_mcp(payload: dict[str, Any]) -> dict[str, Any]:
    name = _name(payload.get("name"))
    action = str(payload.get("action") or "save")
    config = load_global_config()
    servers = config.setdefault("mcp", {}).setdefault("servers", {})
    if action == "delete":
        if name not in servers:
            return {"ok": False, "error": f"MCP server not found: {name}"}
        del servers[name]
        save_global_config(config)
        return {"ok": True, "name": name, "removed": True}
    command = str(payload.get("command") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not command and not url:
        return {"ok": False, "error": "Choose a local command or remote URL."}
    args = [str(item).strip() for item in (payload.get("args") or []) if str(item).strip()]
    servers[name] = {
        **({"command": command, "args": args} if command else {"url": url}),
        "enabled": bool(payload.get("enabled", True)),
    }
    save_global_config(config)
    return {"ok": True, "name": name, "server": servers[name]}
