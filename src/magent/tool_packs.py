"""Tool capability packs and user-level enablement."""

from __future__ import annotations

from typing import Any

PACKS: dict[str, dict[str, Any]] = {
    "files": {
        "description": "Read, write, inspect, diff, archive, and image-file operations.",
        "tools": [
            "read_file",
            "read_file_range",
            "outline_file",
            "write_file",
            "edit_file",
            "delete_file",
            "list_dir",
            "diff_files",
            "compress",
            "extract",
            "read_image",
            "magent_docs_search",
        ],
    },
    "shell": {
        "description": "Shell, Python subprocess, package install, search, git, and system inspection.",
        "tools": ["run_shell", "run_python", "install_package", "search_codebase", "git_op", "system_info"],
    },
    "web": {
        "description": "Web search, web fetch, and raw HTTP requests.",
        "tools": ["web_search", "web_fetch", "http_request"],
    },
    "data": {
        "description": "Structured local data helpers.",
        "tools": ["json_query"],
    },
    "db": {
        "description": "Named SQLite database query and schema helpers.",
        "tools": ["db_query", "db_execute", "db_list_tables", "db_schema", "db_list_databases"],
    },
    "desktop": {
        "description": "Desktop notification, clipboard, and open-file helpers.",
        "tools": ["notify", "clipboard_read", "clipboard_write", "open_file"],
    },
}


def list_packs(store: Any | None = None) -> list[dict[str, Any]]:
    """List tool packs and enabled state."""
    enabled = enabled_packs(store) if store is not None else set(PACKS)
    return [
        {
            "name": name,
            "enabled": name in enabled,
            "description": spec["description"],
            "tools": spec["tools"],
        }
        for name, spec in sorted(PACKS.items())
    ]


def explain_pack(name: str, store: Any | None = None) -> dict[str, Any]:
    """Explain one capability pack."""
    normalized = name.strip().lower()
    if normalized not in PACKS:
        return {"ok": False, "error": f"Unknown tool pack: {name}", "known": sorted(PACKS)}
    enabled = enabled_packs(store) if store is not None else set(PACKS)
    return {"ok": True, "name": normalized, "enabled": normalized in enabled, **PACKS[normalized]}


def set_pack_enabled(store: Any, name: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable a capability pack for selective tool loading."""
    normalized = name.strip().lower()
    if normalized not in PACKS:
        return {"ok": False, "error": f"Unknown tool pack: {name}", "known": sorted(PACKS)}
    config = store.read("tool_packs", {})
    disabled = set(config.get("disabled", []))
    if enabled:
        disabled.discard(normalized)
    else:
        disabled.add(normalized)
    config = {"disabled": sorted(disabled)}
    store.write("tool_packs", config)
    return {"ok": True, "pack": normalized, "enabled": enabled, "disabled": config["disabled"]}


def enabled_packs(store: Any | None) -> set[str]:
    """Return enabled capability pack names."""
    if store is None:
        return set(PACKS)
    config = store.read("tool_packs", {})
    disabled = set(config.get("disabled", [])) if isinstance(config, dict) else set()
    return set(PACKS) - disabled


def filter_tool_definitions(definitions: list[dict[str, Any]], store: Any | None) -> list[dict[str, Any]]:
    """Filter OpenAI tool definitions by enabled capability packs."""
    enabled_tools: set[str] = set()
    for name in enabled_packs(store):
        enabled_tools.update(PACKS.get(name, {}).get("tools", []))
    return [item for item in definitions if item.get("function", {}).get("name") in enabled_tools]


def filter_tool_definitions_for_user(definitions: list[dict[str, Any]], username: str) -> list[dict[str, Any]]:
    """Best-effort filter for agent runtime tool definitions."""
    try:
        from magent.workbench import WorkbenchStore

        return filter_tool_definitions(definitions, WorkbenchStore(username))
    except Exception:
        return definitions
