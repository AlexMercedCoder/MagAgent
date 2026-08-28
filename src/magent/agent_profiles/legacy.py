"""In-memory conversion of MagAgent's legacy Markdown agents to OAP v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KNOWN = {
    "name",
    "description",
    "mode",
    "provider",
    "model",
    "tools",
    "permissionMode",
    "permission_mode",
    "memory",
    "memory_mode",
    "maxTurns",
    "max_turns",
}


def convert_legacy(path: Path, metadata: dict[str, Any], body: str) -> dict[str, Any]:
    name = str(metadata.get("name") or path.stem).strip().lower()
    spec: dict[str, Any] = {"role": {"instructions": body.strip()}}
    model: dict[str, Any] = {}
    if metadata.get("provider"):
        model["provider"] = str(metadata["provider"])
    if metadata.get("model"):
        model["id"] = str(metadata["model"])
    if model:
        spec["model"] = model
    tools = metadata.get("tools")
    if isinstance(tools, dict):
        allow = [str(key) for key, value in tools.items() if value is True or value == "allow"]
        deny = [str(key) for key, value in tools.items() if value is False or value == "deny"]
        spec["tools"] = {"allow": allow, "deny": deny}
    permission = metadata.get("permissionMode") or metadata.get("permission_mode")
    if permission:
        modes = {"paranoid": "deny", "balanced": "ask", "silent": "allow", "yolo": "allow"}
        spec["permissions"] = {"default": modes.get(str(permission), str(permission))}
    memory = metadata.get("memory") or metadata.get("memory_mode")
    if memory:
        mode = {"read": "read_only", "write": "read_write"}.get(str(memory), "read_only")
        spec["memory"] = {"stores": [{"name": "legacy-memory", "kind": "custom", "mode": mode}]}
    max_turns = metadata.get("maxTurns") or metadata.get("max_turns")
    runtime: dict[str, Any] = {"mode": str(metadata.get("mode") or "subagent")}
    if max_turns:
        runtime["max_turns"] = int(max_turns)
    spec["runtime"] = runtime
    spec["lifecycle"] = {"writeback": "propose"}
    annotations = {key: value for key, value in metadata.items() if key not in KNOWN}
    return {
        "oap": "1.0",
        "kind": "AgentProfile",
        "metadata": {
            "name": name,
            "description": str(metadata.get("description") or name),
            "revision": 1,
            **(
                {"annotations": {"magagent.dev/legacy": json.dumps(annotations, sort_keys=True)}}
                if annotations
                else {}
            ),
        },
        "spec": spec,
        "state": {},
        "history": [],
    }


def legacy_frontmatter(document: dict[str, Any]) -> dict[str, Any]:
    spec = document.get("spec", {})
    metadata = document.get("metadata", {})
    model = spec.get("model", {})
    runtime = spec.get("runtime", {})
    tools = spec.get("tools", {})
    result: dict[str, Any] = {
        "name": metadata.get("name", ""),
        "description": metadata.get("description", ""),
        "mode": runtime.get("mode", "subagent"),
        "provider": model.get("provider", ""),
        "model": model.get("id", ""),
        "tools": tools.get("legacy_bindings", {}),
        "permissionMode": spec.get("permissions", {}).get("default", ""),
        "memory": spec.get("memory", {}).get("mode", ""),
        "maxTurns": runtime.get("max_turns", 0),
    }
    return result
