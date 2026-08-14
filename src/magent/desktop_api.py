"""Machine-readable APIs intended for desktop/app integrations."""

from __future__ import annotations

import json
import platform
import shutil
import sys
from hashlib import sha256
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
from magent.permissions import PERMISSION_MODES
from magent.task_runtime import TaskRuntime, TaskRuntimeError, TaskState
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
        "choices": sorted(PERMISSION_MODES),
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
    {
        "path": "session_messaging.policy",
        "label": "Session message policy",
        "type": "enum",
        "scope": "global",
        "category": "agents",
        "choices": ["accept", "hold", "refuse"],
        "description": "Default policy for local messages from other MagAgent sessions.",
    },
    {
        "path": "session_messaging.headless_accept",
        "label": "Allow headless session messages",
        "type": "boolean",
        "scope": "global",
        "category": "agents",
        "description": "Allow non-interactive sessions to accept peer text without inbox review.",
    },
]


def system_info() -> dict[str, Any]:
    """Return desktop-friendly local MagAgent installation info."""
    from magent.agraph.mappings import TIER_TO_MODEL_ROLE, TOOL_NAME_MAP

    username = get_current_user()
    executable = shutil.which("magent") or ""
    return {
        "ok": True,
        "magent_version": __version__,
        "agentic_graph": {
            "spec_version": "1.0",
            "conformance_level": 3,
            "supported_features": [
                "validation",
                "planning",
                "task",
                "decision",
                "gate",
                "loop",
                "map",
                "subgraph",
                "criteria",
                "retries",
                "budgets",
                "parallelism",
                "run-records",
                "resume",
                "generation",
            ],
            "tier_to_model_role": dict(TIER_TO_MODEL_ROLE),
            "logical_tool_mapping": {name: list(tools) for name, tools in TOOL_NAME_MAP.items()},
        },
        "open_agent_profile": {
            "spec_version": "1.0",
            "conformance_level": 2,
            "encodings": ["yaml", "json", "md"],
        },
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


def platform_contracts() -> dict[str, Any]:
    """Return stable machine interfaces and their compatibility status."""
    from magent.task_runtime import EVENT_SCHEMA_VERSION, TASK_SCHEMA_VERSION

    return {
        "ok": True,
        "schema": "magent.platform-contracts.v1",
        "magent_version": __version__,
        "release_candidate": "1.0",
        "contracts": {
            "desktop_cli": {"version": "1", "status": "stable", "transport": "json/jsonl"},
            "task": {"version": TASK_SCHEMA_VERSION, "status": "stable"},
            "task_event": {"version": EVENT_SCHEMA_VERSION, "status": "stable"},
            "plugin_manifest": {"version": "1", "status": "stable"},
            "plugin_registry": {"version": "magent.plugin-registry.v1", "status": "beta"},
            "provider_support": {"version": "magent.provider-support.v1", "status": "stable"},
            "ecosystem_readiness": {"version": "mag.ecosystem-readiness.v1", "status": "beta"},
            "config_schema": {"version": "1", "status": "stable"},
            "memory_batch": {"version": "1", "status": "stable", "requires": "maggraph>=0.4.1"},
            "memory_recall": {"version": "2", "status": "stable", "requires": "maggraph>=0.4.1"},
            "persistent_state": {"version": "1", "status": "stable"},
            "supply_chain": {"version": "magent.supply-chain.v1", "status": "stable"},
            "agentic_graph": {
                "version": "1.0",
                "status": "draft-standard",
                "conformance_level": 3,
                "transport": "json/jsonl",
            },
            "open_agent_profile": {
                "version": "1.0",
                "status": "beta",
                "conformance_level": 2,
                "transport": "json",
            },
            "mcp": {
                "status": "dual-era-core",
                "legacy_through": "2025-11-25",
                "modern": "2026-07-28",
                "experimental": ["tasks", "remote-skills", "apps-rendering"],
            },
        },
        "support": {
            "python": ["3.11", "3.12", "3.13", "3.14"],
            "deprecation_notice_minor_releases": 1,
            "breaking_changes_before_1_0": "frozen after 0.90; security exceptions only",
        },
    }


def agent_profiles(project: str = ".") -> dict[str, Any]:
    """Return resolved OAP metadata for desktop clients."""
    from magent.agent_profiles.registry import AgentProfileRegistry

    username = get_current_user()
    config = load_config(username) if username else None
    return AgentProfileRegistry(project, config).list()


def agent_profile(name: str, project: str = ".", *, effective: bool = False) -> dict[str, Any]:
    """Return one resolved or effective profile as machine-readable JSON."""
    from magent.agent_profiles.registry import AgentProfileRegistry

    username = get_current_user()
    config = load_config(username) if username else None
    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None:
        return {"ok": False, "error": f"Agent profile not found: {name}"}
    if not effective:
        return {"ok": True, "profile": resolved.as_dict()}
    if config is None:
        return {"ok": False, "error": "No configured user; effective policy is unavailable"}
    from magent.agent_profiles.effective import resolve_effective_profile
    from magent.tools.catalog import built_in_tool_definitions

    granted = {item.get("function", {}).get("name", "") for item in built_in_tool_definitions()}
    return {"ok": True, "effective_profile": resolve_effective_profile(resolved, config, granted).as_dict()}


def agent_profile_inbox(project: str = ".") -> dict[str, Any]:
    """Return pending profile deltas for a desktop review surface."""
    from magent.agent_profiles.delta import ProfileDeltaInbox

    return {"ok": True, "deltas": ProfileDeltaInbox(project).pending()}


def graph_validate(path: str, *, strict: bool = False) -> dict[str, Any]:
    """Validate a graph for desktop clients without executing it."""
    from magent.agraph.validate import validate_graph

    return validate_graph(path, strict=strict).as_dict()


def graph_plan(path: str) -> dict[str, Any]:
    """Return a render-ready graph plan."""
    from magent.agraph.plan import plan_graph

    try:
        return plan_graph(path).as_dict()
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def graph_catalog(username: str) -> dict[str, Any]:
    """Return saved graph documents and recent portable run records."""
    from magent.workbench_store import WorkbenchStore

    store = WorkbenchStore(username)
    return {
        "ok": True,
        "graphs": store.read("graphs", []),
        "runs": list(reversed(store.read("graph_runs", [])))[:100],
    }


async def graph_execute(
    username: str,
    path: str,
    *,
    project: str = ".",
    params: dict[str, Any] | None = None,
    assume_yes: bool = False,
) -> dict[str, Any]:
    """Execute a graph through the same runtime used by the CLI."""
    from magent.agraph.execute import GraphExecutor
    from magent.workbench_store import WorkbenchStore

    return await GraphExecutor(
        username=username,
        config=load_config(username),
        project=project,
        store=WorkbenchStore(username),
        assume_yes=assume_yes,
    ).run(path, params=params or {})


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
            "global": redact_config_text(GLOBAL_CONFIG.read_text(encoding="utf-8"))
            if GLOBAL_CONFIG.exists()
            else "",
            "user": redact_config_text(
                (USERS_DIR / username / "profile.toml").read_text(encoding="utf-8")
            )
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
    if not parts:
        # `path="."` used to reach parts[-1] and raise IndexError.
        return {"ok": False, "error": "path must name at least one config key"}
    if path.strip() == "defaults.permission_mode" and str(value) not in PERMISSION_MODES:
        # A desktop client could silently set yolo (all gating off).
        return {
            "ok": False,
            "error": f"permission_mode must be one of {', '.join(sorted(PERMISSION_MODES))}",
        }
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
    nodes = (
        mgr.search(query or "*", max_results=limit, mode="keyword")
        if query
        else mgr.export_json()[:limit]
    )
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
        "backlinks": mgr.backlinks(node_id),
        "traversal": mgr.traverse_node(node_id, depth=1),
    }


def memory_recall(
    username: str,
    query: str,
    *,
    project: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """Return render-ready recall results plus the bounded context packet."""
    mgr = MemoryManager(
        user_memory_dir(username),
        username=username,
        project_slug=project or None,
    )
    results = mgr.search(query, max_results=max(1, min(limit, 50)), mode="hybrid")
    context = mgr.recall(query)
    return {
        "ok": True,
        "schema": "magent.memory-recall.v2",
        "user": username,
        "project": project,
        "query": query,
        "results": results,
        "context": context,
        "context_stats": dict(mgr.last_recall_stats),
    }


def memory_update_node(
    username: str,
    node_id: str,
    *,
    body: str | None = None,
    links: list[str] | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    """Update a memory node body and optional links for desktop editors."""
    mgr = MemoryManager(user_memory_dir(username), username=username)
    before = mgr.read_node(node_id)
    if not before:
        return {"ok": False, "error": f"Node not found: {node_id}"}
    next_body = before.get("body", "") if body is None else body
    before_hash = _body_hash(before.get("body", ""))
    after_hash = _body_hash(next_body)
    if preview:
        return {
            "ok": True,
            "preview": True,
            "id": node_id,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "old_chars": len(before.get("body", "")),
            "new_chars": len(next_body),
            "links": links if links is not None else before.get("links", []),
        }
    result = mgr.update_node(node_id, body=body, links=links)
    if result.get("ok"):
        result["node"] = mgr.read_node(node_id)
        result["before_hash"] = before_hash
        result["after_hash"] = after_hash
    return result


def memory_apply_batch(
    username: str,
    operations: list[dict[str, str]],
    *,
    preview: bool = False,
) -> dict[str, Any]:
    """Preview or apply a reviewed set of memory graph operations."""
    mgr = MemoryManager(user_memory_dir(username), username=username)
    return mgr.apply_batch(operations, preview=preview)


def sqlite_list(username: str) -> dict[str, Any]:
    return list_databases(username)


def sqlite_tables(username: str, db_name: str = "default") -> dict[str, Any]:
    return db_list_tables(username, db_name)


def sqlite_table_schema(username: str, table: str, db_name: str = "default") -> dict[str, Any]:
    return db_schema(username, table, db_name)


def sqlite_query(
    username: str, sql: str, db_name: str = "default", params: list[Any] | None = None
) -> dict[str, Any]:
    return db_query(username, sql, params=params, db_name=db_name)


def session_messaging_state(
    username: str,
    *,
    session_id: str = "",
    held: bool = False,
) -> dict[str, Any]:
    """Return desktop-friendly peer and optional inbox state."""
    from magent.session_messaging import list_sessions, session_inbox

    peers = list_sessions(username)
    messages = session_inbox(username, session_id, held=held) if session_id else []
    return {"ok": True, "sessions": peers, "messages": messages, "held": held}


def session_message_send(
    username: str,
    target: str,
    message: str,
    *,
    task_id: str = "",
    cwd: str = "",
) -> dict[str, Any]:
    """Send a desktop-originated message without exposing a capability."""
    from magent.session_messaging import register_ephemeral_sender, send_session_message

    sender_id, cleanup = register_ephemeral_sender(username, name="command-center", cwd=cwd)
    try:
        return send_session_message(username, sender_id, target, message, task_id=task_id)
    finally:
        cleanup()


def session_message_review(
    username: str,
    session_id: str,
    message_id: str,
    decision: str,
) -> dict[str, Any]:
    """Accept or refuse a held message from a desktop client."""
    from magent.session_messaging import review_held_message

    return review_held_message(username, session_id, message_id, decision)


def execution_tasks(
    username: str,
    *,
    state: TaskState | None = None,
    project_id: str = "",
    parent_task_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return durable execution tasks for desktop clients."""
    runtime = TaskRuntime(USERS_DIR / username / "workbench")
    return {
        "ok": True,
        "tasks": runtime.list_tasks(
            state=state,
            project_id=project_id,
            parent_task_id=parent_task_id,
            limit=limit,
        ),
    }


def execution_task(
    username: str, task_id: str, *, after: int = 0, limit: int = 500
) -> dict[str, Any]:
    """Return one task and its ordered event stream."""
    runtime = TaskRuntime(USERS_DIR / username / "workbench")
    task = runtime.get(task_id)
    if task is None:
        return {"ok": False, "error": f"Task not found: {task_id}"}
    return {"ok": True, "task": task, "events": runtime.events(task_id, after=after, limit=limit)}


def execution_task_action(
    username: str, task_id: str, action: str, *, reason: str = ""
) -> dict[str, Any]:
    """Pause, resume, cancel, or retry a durable execution task."""
    runtime = TaskRuntime(USERS_DIR / username / "workbench")
    if action not in {"pause", "resume", "cancel", "retry"}:
        return {"ok": False, "error": f"Unsupported task action: {action}"}
    try:
        operation = getattr(runtime, action)
        task = operation(task_id, reason=reason or f"{action.title()} requested by desktop client")
    except TaskRuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "task": task}


def parse_json_value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"api_key_env", "api_key_keyring", "api_key_command", "api_key_file"}:
                redacted[key] = item
                continue
            if any(
                secret in lowered
                for secret in (
                    "api_key",
                    "apikey",
                    "access_key",
                    "secret",
                    "token",
                    "password",
                    "passwd",
                    "credential",
                    "bearer",
                    "private_key",
                    "auth",
                )
            ):
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


def _body_hash(body: str) -> str:
    return sha256(body.encode("utf-8")).hexdigest()[:16]
