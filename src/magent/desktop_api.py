"""Machine-readable APIs intended for desktop/app integrations."""

from __future__ import annotations

import json
import platform
import shutil
import sys
from typing import Any

from magent import __version__
from magent.config import (
    CONFIG_DIR,
    GLOBAL_CONFIG,
    USERS_DIR,
    get_current_user,
    load_config,
    load_global_config,
    load_user_profile,
    save_global_config,
    save_user_profile,
    user_exists,
    user_memory_dir,
)
from magent.config_safety import redact_config_text
from magent.memory import MemoryManager
from magent.tools.db import db_list_tables, db_query, db_schema, list_databases

CONFIG_SCHEMA: list[dict[str, Any]] = [
    {
        "path": "defaults.provider",
        "label": "Default provider",
        "type": "string",
        "scope": "global",
        "category": "provider",
        "description": "Provider ID used when no provider is supplied.",
    },
    {
        "path": "defaults.model",
        "label": "Default model",
        "type": "string",
        "scope": "global",
        "category": "provider",
        "description": "Model name used for the main agent by default.",
    },
    {
        "path": "defaults.permission_mode",
        "label": "Permission mode",
        "type": "enum",
        "scope": "global",
        "category": "permissions",
        "choices": ["balanced", "ask", "strict", "paranoid", "permissive", "silent", "yolo"],
        "description": "Default tool permission posture.",
    },
    {
        "path": "memory.auto_write",
        "label": "Memory auto-write",
        "type": "boolean",
        "scope": "global",
        "category": "memory",
        "description": "Allow MagAgent to write durable memories automatically.",
    },
    {
        "path": "memory.semantic_enabled",
        "label": "Semantic memory",
        "type": "boolean",
        "scope": "global",
        "category": "memory",
        "description": "Enable semantic sidecar recall when configured.",
    },
    {
        "path": "subagents.max_subagents",
        "label": "Max subagents",
        "type": "integer",
        "scope": "global",
        "category": "subagents",
        "min": 0,
        "description": "Maximum number of subagents a primary agent may orchestrate.",
    },
    {
        "path": "subagents.max_parallel_subagents",
        "label": "Max parallel subagents",
        "type": "integer",
        "scope": "global",
        "category": "subagents",
        "min": 0,
        "description": "Maximum concurrent subagents.",
    },
    {
        "path": "ui.theme",
        "label": "CLI/TUI theme",
        "type": "enum",
        "scope": "global",
        "category": "ui",
        "choices": ["light", "dark", "system"],
        "description": "Preferred MagAgent interface theme.",
    },
]


def system_info() -> dict[str, Any]:
    """Return desktop-friendly local MagAgent installation info."""
    username = get_current_user()
    executable = shutil.which("magent") or ""
    return {
        "ok": True,
        "magent_version": __version__,
        "python": sys.version.split()[0],
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "paths": {
            "config_dir": str(CONFIG_DIR),
            "global_config": str(GLOBAL_CONFIG),
            "users_dir": str(USERS_DIR),
            "magent_executable": executable,
        },
        "current_user": username,
        "user_exists": bool(username and user_exists(username)),
    }


def config_get(username: str | None = None, *, include_raw: bool = False) -> dict[str, Any]:
    """Return global, user, and merged config without exposing secrets."""
    username = username or get_current_user() or "default"
    global_cfg = load_global_config()
    user_cfg = load_user_profile(username) if user_exists(username) else {}
    merged = load_config(username).as_dict() if user_exists(username) else global_cfg
    result: dict[str, Any] = {
        "ok": True,
        "user": username,
        "paths": {
            "global": str(GLOBAL_CONFIG),
            "user": str(USERS_DIR / username / "profile.toml"),
        },
        "global": _redact_obj(global_cfg),
        "user_config": _redact_obj(user_cfg),
        "merged": _redact_obj(merged),
    }
    if include_raw:
        result["raw"] = {
            "global": redact_config_text(GLOBAL_CONFIG.read_text(encoding="utf-8")) if GLOBAL_CONFIG.exists() else "",
            "user": redact_config_text((USERS_DIR / username / "profile.toml").read_text(encoding="utf-8"))
            if (USERS_DIR / username / "profile.toml").exists()
            else "",
        }
    return result


def config_set(
    path: str,
    value: Any,
    *,
    username: str | None = None,
    scope: str = "global",
) -> dict[str, Any]:
    """Set a dot-path config value in global config or current user profile."""
    if not path.strip():
        return {"ok": False, "error": "path is required"}
    username = username or get_current_user() or "default"
    cfg = load_user_profile(username) if scope == "user" else load_global_config()
    node = cfg
    parts = [part for part in path.split(".") if part]
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            return {"ok": False, "error": f"Cannot set through non-object path segment: {part}"}
    node[parts[-1]] = value
    if scope == "user":
        save_user_profile(username, cfg)
    elif scope == "global":
        save_global_config(cfg)
    else:
        return {"ok": False, "error": "scope must be global or user"}
    return {"ok": True, "scope": scope, "user": username, "path": path, "value": _redact_obj(value)}


def config_schema(username: str | None = None) -> dict[str, Any]:
    """Return desktop-friendly metadata for common guided config controls."""
    cfg = config_get(username)
    merged = cfg.get("merged", {})
    fields = []
    for item in CONFIG_SCHEMA:
        field = dict(item)
        field["value"] = _lookup_path(merged, item["path"])
        fields.append(field)
    return {
        "ok": True,
        "user": cfg.get("user"),
        "paths": cfg.get("paths", {}),
        "fields": fields,
        "raw_edit_supported": True,
    }


def memory_graph(username: str, *, query: str = "", limit: int = 100) -> dict[str, Any]:
    """Return a compact graph view suitable for desktop browsing."""
    mgr = MemoryManager(user_memory_dir(username), username=username)
    stats = mgr.stats()
    nodes = mgr.search(query or "*", max_results=limit, mode="keyword") if query else mgr.export_json()[:limit]
    return {
        "ok": True,
        "user": username,
        "stats": stats,
        "nodes": nodes,
        "count": len(nodes),
    }


def memory_node(username: str, node_id: str) -> dict[str, Any]:
    """Return one memory node plus traversal/provenance context."""
    mgr = MemoryManager(user_memory_dir(username), username=username)
    node = mgr.read_node(node_id)
    if not node:
        return {"ok": False, "error": f"Node not found: {node_id}"}
    return {
        "ok": True,
        "user": username,
        "node": node,
        "traversal": mgr.traverse_node(node_id, depth=1),
    }


def memory_update_node(
    username: str,
    node_id: str,
    *,
    body: str | None = None,
    links: list[str] | None = None,
) -> dict[str, Any]:
    """Update a memory node body and optional links for desktop editors."""
    mgr = MemoryManager(user_memory_dir(username), username=username)
    result = mgr.update_node(node_id, body=body, links=links)
    if result.get("ok"):
        result["node"] = mgr.read_node(node_id)
    return result


def sqlite_list(username: str) -> dict[str, Any]:
    return list_databases(username)


def sqlite_tables(username: str, db_name: str = "default") -> dict[str, Any]:
    return db_list_tables(username, db_name)


def sqlite_table_schema(username: str, table: str, db_name: str = "default") -> dict[str, Any]:
    return db_schema(username, table, db_name)


def sqlite_query(username: str, sql: str, db_name: str = "default", params: list[Any] | None = None) -> dict[str, Any]:
    return db_query(username, sql, params=params, db_name=db_name)


def parse_json_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if any(secret in str(key).lower() for secret in ("api_key", "token", "secret", "password")):
                redacted[key] = "***" if item else item
            else:
                redacted[key] = _redact_obj(item)
        return redacted
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    return value


def _lookup_path(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
