"""Reviewed lifecycle operations for extensions in the local Web UI."""

from __future__ import annotations

import asyncio
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
        'version: "1.0"\n'
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
    existing = servers.get(name) if isinstance(servers.get(name), dict) else {}
    candidate = _mcp_candidate(payload, existing=existing)
    from magent.mcp.profile import MCPConfigError, MCPServerProfile

    try:
        MCPServerProfile.from_config(name, candidate)
    except MCPConfigError as error:
        return {"ok": False, "error": str(error)}
    servers[name] = candidate
    save_global_config(config)
    return {"ok": True, "name": name, "server": servers[name]}


def _mapping(value: Any, *, existing: dict[str, Any] | None = None) -> dict[str, str]:
    if value is None:
        return dict(existing or {})
    if not isinstance(value, dict):
        raise ValueError("Environment variables and headers must be name/value pairs.")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        item = str(raw_value or "").strip()
        if not key or not item:
            raise ValueError(
                "Environment variables and headers cannot contain blank names or values."
            )
        if item == "[configured]" and key in (existing or {}):
            item = str((existing or {})[key])
        result[key] = item
    return result


def _mcp_candidate(
    payload: dict[str, Any], *, existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    existing = existing or {}
    transport = str(
        payload.get("transport") or ("streamable-http" if payload.get("url") else "stdio")
    )
    command = str(payload.get("command") or "").strip()
    url = str(payload.get("url") or "").strip()
    args = [str(item).strip() for item in (payload.get("args") or []) if str(item).strip()]
    env = _mapping(payload.get("env"), existing=existing.get("env"))
    headers = _mapping(payload.get("headers"), existing=existing.get("headers"))
    candidate: dict[str, Any] = {
        "transport": transport,
        "protocol_mode": str(payload.get("protocol_mode") or "auto"),
        "enabled": bool(payload.get("enabled", True)),
        "timeout": float(payload.get("timeout") or 30),
    }
    if transport == "stdio":
        candidate.update(command=command, args=args)
        if str(payload.get("cwd") or "").strip():
            candidate["cwd"] = str(payload.get("cwd")).strip()
        if env:
            candidate["env"] = env
    else:
        candidate["url"] = url
        if headers:
            candidate["headers"] = headers
    if transport == "legacy-sse":
        candidate["allow_deprecated_transport"] = bool(
            payload.get("allow_deprecated_transport", False)
        )
    return candidate


def test_mcp(payload: dict[str, Any]) -> dict[str, Any]:
    """Connect once with an unsaved server definition and return redacted diagnostics."""

    from magent.mcp.client import MCPClient
    from magent.mcp.profile import MCPConfigError, MCPServerProfile

    name = _name(payload.get("name"))
    try:
        profile = MCPServerProfile.from_config(name, _mcp_candidate(payload))
    except (MCPConfigError, ValueError) as error:
        return {"ok": False, "error": str(error)}

    async def probe() -> dict[str, Any]:
        client = MCPClient.from_profile(profile)
        connected = await client.connect()
        try:
            status = client.public_status()
            return {
                "ok": connected,
                "message": (
                    f"Connected to {name}; discovered {len(status.get('tools') or [])} tools."
                    if connected
                    else status.get("error") or f"Could not connect to {name}."
                ),
                "status": status,
            }
        finally:
            await client.disconnect()

    return asyncio.run(probe())


def public_mcp_config(value: dict[str, Any]) -> dict[str, Any]:
    """Expose editable structure without returning literal credential values."""

    def safe_mapping(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        result = {}
        for key, item in raw.items():
            text = str(item)
            result[str(key)] = text if "$" in text else "[configured]"
        return result

    return {
        "enabled": bool(value.get("enabled", True)),
        "transport": str(
            value.get("transport") or ("streamable-http" if value.get("url") else "stdio")
        ),
        "protocol_mode": str(value.get("protocol_mode") or "auto"),
        "command": str(value.get("command") or ""),
        "args": list(value.get("args") or []),
        "cwd": str(value.get("cwd") or ""),
        "url": str(value.get("url") or ""),
        "env": safe_mapping(value.get("env")),
        "headers": safe_mapping(value.get("headers")),
        "timeout": float(value.get("timeout") or 30),
        "allow_deprecated_transport": bool(value.get("allow_deprecated_transport", False)),
    }
