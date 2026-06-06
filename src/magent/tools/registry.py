"""Tool schema and registry helpers."""

from __future__ import annotations

from typing import Any


def tool_def(name: str, description: str, params: dict[str, tuple[str, str | None]]) -> dict[str, Any]:
    """Build an OpenAI-compatible tool definition."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, (param_type, param_desc) in params.items():
        prop: dict[str, Any] = {"type": param_type}
        if param_type == "array":
            prop["items"] = {}
        if param_desc:
            prop["description"] = param_desc
        desc = (param_desc or "").lower()
        if "optional" not in desc and "default" not in desc:
            required.append(param_name)
        properties[param_name] = prop

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
