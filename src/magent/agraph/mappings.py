"""Published AGS-to-MagAgent routing and capability mappings."""

from __future__ import annotations

TIER_TO_MODEL_ROLE = {
    "minimal": "cheap",
    "standard": "coding",
    "advanced": "coding",
    "frontier": "frontier",
}

TOOL_NAME_MAP = {
    "file_read": ("read_file", "list_dir", "outline_file"),
    "file_search": ("search_codebase",),
    "file_write": ("write_file", "edit_file", "apply_patch"),
    "shell_exec": ("run_shell",),
    "web_search": ("web_search", "deep_research"),
    "web_fetch": ("web_fetch", "http_request"),
    "http_fetch": ("web_fetch", "http_request"),
    "browser": ("browser_snapshot", "browser_screenshot", "browser_click"),
    "data": ("query_json", "query_csv", "query_parquet"),
    "database": ("db_query", "db_schema", "db_list_tables"),
    "image": ("generate_image", "create_svg", "create_diagram"),
    "document": ("create_document", "create_presentation"),
    "memory": ("memory_search", "memory_write"),
    "session_message": ("session_send", "session_inbox"),
}


def mapped_tools(logical_name: str) -> tuple[str, ...]:
    return TOOL_NAME_MAP.get(logical_name, (logical_name,))


def tool_requirement(item: str | dict[str, object]) -> tuple[str, bool, tuple[str, ...]]:
    """Normalize the string and object forms defined by the AGS schema."""
    if isinstance(item, str):
        return item, False, ()
    return (
        str(item.get("name", "")),
        bool(item.get("optional", False)),
        tuple(str(value) for value in item.get("alternatives", []) if str(value)),
    )


def tools_for_requirement(item: str | dict[str, object]) -> tuple[str, ...]:
    name, _optional, alternatives = tool_requirement(item)
    names = (name, *alternatives)
    return tuple(dict.fromkeys(tool for logical in names for tool in mapped_tools(logical)))
