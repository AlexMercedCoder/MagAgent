"""Shared tool types and budget constants."""

from __future__ import annotations

from typing import Any

ToolResult = dict[str, Any]

READ_FILE_PREVIEW_CHARS = 16000

# Result keys holding opaque/binary payloads. Truncating these produces data
# that no longer decodes, so they are dropped rather than cut.
OPAQUE_RESULT_KEYS = frozenset({"base64", "image_base64", "data_base64", "bytes_base64", "content_base64"})

DEFAULT_TOOL_BUDGETS = {
    "default": 8000,
    "read_file": 16000,
    "read_file_range": 12000,
    "web_fetch": 12000,
    "deep_research": 18000,
    "run_shell": 10000,
    "run_python": 10000,
    "search_codebase": 9000,
    "db_query": 8000,
}
