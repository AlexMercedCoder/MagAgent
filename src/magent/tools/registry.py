"""Tool schema and registry helpers."""

from __future__ import annotations

from typing import Any

TOOL_ACTIVITY_PHASES = [
    "inspect",
    "edit",
    "verify",
    "research",
    "recover",
    "summarize",
    "plan",
    "memory",
    "configure",
    "other",
]


TOOL_ACTIVITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Optional short user-facing activity metadata for diagnostics and UI display. "
        "Do not include hidden chain-of-thought."
    ),
    "properties": {
        "phase": {
            "type": "string",
            "enum": TOOL_ACTIVITY_PHASES,
            "description": "Short workflow phase for this tool call.",
        },
        "intent": {
            "type": "string",
            "description": "Brief user-facing reason for using this tool.",
        },
        "expected": {
            "type": "string",
            "description": "Brief expected outcome from this tool call.",
        },
    },
    "additionalProperties": False,
}


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
    properties["activity"] = TOOL_ACTIVITY_SCHEMA

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


def validate_tool_args(definition: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Validate required arguments from a tool definition."""
    fn = definition.get("function", {})
    params = fn.get("parameters", {})
    required = params.get("required") or []
    missing = [name for name in required if args.get(name) is None]
    return {"ok": not missing, "missing": missing, "tool": fn.get("name", "")}


def normalize_tool_activity(args: dict[str, Any] | None) -> dict[str, str]:
    """Return sanitized optional tool activity metadata."""
    if not isinstance(args, dict):
        return {}
    raw = args.get("activity")
    if not isinstance(raw, dict):
        return {}
    activity: dict[str, str] = {}
    phase = str(raw.get("phase") or "").strip().lower()
    if phase in TOOL_ACTIVITY_PHASES:
        activity["phase"] = phase
    for key, limit in (("intent", 180), ("expected", 180)):
        value = str(raw.get(key) or "").strip()
        if value:
            activity[key] = value[:limit]
    return activity


def strip_tool_activity(args: dict[str, Any] | None) -> dict[str, Any]:
    """Remove display-only activity metadata before validating or executing tools."""
    if not isinstance(args, dict):
        return {}
    stripped = dict(args)
    stripped.pop("activity", None)
    return stripped
