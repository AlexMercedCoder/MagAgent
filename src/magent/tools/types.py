"""Shared tool types and budget constants."""

from __future__ import annotations

from typing import Any

ToolResult = dict[str, Any]

READ_FILE_PREVIEW_CHARS = 16000

DEFAULT_TOOL_BUDGETS = {
    "default": 8000,
    "read_file": 16000,
    "read_file_range": 12000,
    "web_fetch": 12000,
    "run_shell": 10000,
    "run_python": 10000,
    "search_codebase": 9000,
    "db_query": 8000,
}
