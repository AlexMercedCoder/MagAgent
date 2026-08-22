"""Machine-readable Agentic Graph authoring contracts for desktop clients."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from magent.agraph.document import graph_digest, load_graph
from magent.agraph.generate import generate_graph_document
from magent.agraph.plan import resolved_plan
from magent.agraph.validate import validate_graph

CONTRACT_VERSION = "magent.agentic-graph-authoring.v2"
NODE_TYPES = ("task", "decision", "gate", "loop", "map", "subgraph")


def node_template(node_type: str, index: int = 1) -> dict[str, Any]:
    """Return a conservative, strictly-valid starter node for a visual editor."""
    if node_type not in NODE_TYPES:
        raise ValueError(f"Unsupported node type: {node_type}")
    base: dict[str, Any] = {
        "type": node_type,
        "title": f"New {node_type} {index}",
        "description": f"Configure the {node_type} outcome and review it before execution.",
    }
    if node_type == "task":
        base.update({
            "intelligence": {"tier": "standard"},
            "requirements": {"tools": ["file_read"], "permissions": ["fs:read:**"], "workspace": "read_only"},
            "constraints": {"max_agent_steps": 16, "max_wall_clock_seconds": 900},
            "failure": {"retry": {"max_attempts": 2, "retry_on": ["transient", "criteria_failed"]}, "on_exhausted": "fail"},
            "estimate": {"effort": "s", "cost_usd": 0.2},
        })
    elif node_type == "decision":
        base["decision"] = {"question": "Which reviewed path should run?", "branches": [{"label": "continue", "description": "Continue with the default path."}]}
        base["intelligence"] = {"tier": "standard"}
    elif node_type == "gate":
        base["gate"] = {"mode": "approve", "prompt": "Approve this graph checkpoint?", "on_reject": "fail"}
    elif node_type in {"loop", "map"}:
        body = {"entrypoints": ["work"], "nodes": {"work": node_template("task", 1)}}
        if node_type == "loop":
            base["loop"] = {"mode": "repeat", "max_iterations": 1, "body": body}
        else:
            base["map"] = {"over": "[]", "as": "item", "max_items": 10, "max_parallel": 1, "body": body}
    else:
        base["subgraph"] = {"inline": {"entrypoints": ["work"], "nodes": {"work": node_template("task", 1)}}, "inherit_context": False}
    return base


def authoring_contract(project: str | Path = ".", config: Any | None = None) -> dict[str, Any]:
    from magent.agent_profiles.registry import AgentProfileRegistry

    schema_path = Path(__file__).parent / "schema" / "agentic-graph-1.0.schema.json"
    profiles = AgentProfileRegistry(project, config).list()
    return {
        "ok": True,
        "contract": CONTRACT_VERSION,
        "graph_spec": "1.0",
        "profile_extension": "x-magagent-profile",
        "node_types": list(NODE_TYPES),
        "node_templates": {kind: node_template(kind) for kind in NODE_TYPES},
        "graph_templates": _trusted_plugin_graph_templates(),
        "profiles": profiles["profiles"],
        "warnings": profiles["warnings"],
        "schema": json.loads(schema_path.read_text(encoding="utf-8")),
    }


def inspect_graph(path: str | Path, *, strict: bool = True) -> dict[str, Any]:
    document = load_graph(path)
    report = validate_graph(document, strict=strict)
    return {
        "ok": report.ok,
        "contract": CONTRACT_VERSION,
        "path": str(document.path) if document.path else "",
        "digest": document.digest,
        "document": document.data,
        "validation": report.as_dict(),
    }


def preview_graph(document: dict[str, Any], *, project: str | Path = ".", config: Any | None = None) -> dict[str, Any]:
    report = validate_graph(document, strict=True)
    findings = list(report.as_dict().get("findings") or [])
    findings.extend(_profile_findings(document, project, config))
    ok = report.ok and not any(item.get("severity") == "error" for item in findings)
    result: dict[str, Any] = {
        "ok": ok,
        "contract": CONTRACT_VERSION,
        "digest": graph_digest(document),
        "document": document,
        "validation": {**report.as_dict(), "ok": ok, "findings": findings},
    }
    if ok:
        result["plan"] = resolved_plan(document, project=str(project), config=config)
    return result


def save_graph(
    document: dict[str, Any],
    path: str | Path,
    *,
    project: str | Path = ".",
    config: Any | None = None,
    expected_digest: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    target = Path(path).expanduser()
    target = (target if target.is_absolute() else root / target).resolve(strict=False)
    if target != root and root not in target.parents:
        return {"ok": False, "error": "Graph path escapes the active project"}
    preview = preview_graph(document, project=root, config=config)
    if not preview["ok"]:
        return preview
    if target.exists() and expected_digest:
        current = load_graph(target).digest
        if current != expected_digest:
            return {"ok": False, "conflict": True, "error": "Graph changed on disk", "current_digest": current}
    target.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        if target.suffix.lower() == ".json"
        else _yaml_text(document)
    )
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"ok": True, "contract": CONTRACT_VERSION, "path": str(target), "digest": graph_digest(document), "document": document}


def generate_draft(goal: str, *, project: str | Path = ".") -> dict[str, Any]:
    document = generate_graph_document(goal, project=project)
    return {"ok": True, "contract": CONTRACT_VERSION, "document": document, "digest": graph_digest(document)}


async def model_graph_draft(
    goal: str,
    *,
    project: str | Path = ".",
    config: Any,
    document: dict[str, Any] | None = None,
    instruction: str = "",
) -> dict[str, Any]:
    """Ask the configured planning model for a review-only, strictly valid graph proposal."""
    from magent.cli.command_context import build_provider_for_role

    provider = build_provider_for_role(config, "review")
    schema_path = Path(__file__).parent / "schema" / "agentic-graph-1.0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    baseline = document or generate_graph_document(goal, project=project)
    project_root = Path(project).expanduser().resolve()
    prompt = {
        "goal": goal,
        "instruction": instruction or "Improve this graph while preserving a bounded, reviewable workflow.",
        "project": str(project_root),
        "current_graph": baseline,
        "allowed_node_types": list(NODE_TYPES),
        "schema": schema,
    }
    messages = [
        {"role": "system", "content": "Return only one JSON object conforming to the supplied AGS 1.0 schema. Do not use markdown fences. Never widen permissions unless the instruction explicitly requires it."},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    errors: list[str] = []
    for _attempt in range(3):
        raw = await provider.complete(messages, temperature=0.1, max_tokens=12000)
        try:
            proposed = _json_object(raw)
        except ValueError as exc:
            errors.append(str(exc))
            messages.append({"role": "user", "content": f"The response was not a JSON object: {exc}. Return a complete corrected graph JSON object only."})
            continue
        preview = preview_graph(proposed, project=project_root, config=config)
        if preview["ok"]:
            return {
                **preview,
                "proposal": True,
                "model": getattr(provider, "display_name", "planning model"),
                "profile": "planning-role:review",
                "changes": _change_summary(baseline, proposed),
            }
        findings = preview.get("validation", {}).get("findings", [])
        errors.append("; ".join(str(item.get("message")) for item in findings[:12]))
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": "Repair these validation findings and return the entire corrected JSON object only: " + errors[-1]})
    return {"ok": False, "error": "Model proposal did not pass strict validation", "attempts": 3, "findings": errors}


def rename_node(document: dict[str, Any], old_id: str, new_id: str) -> dict[str, Any]:
    """Rename a node and every normative AGS reference to it."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", new_id):
        return {"ok": False, "error": "New node id is not a valid AGS node id"}
    nodes = document.get("nodes") or {}
    if old_id not in nodes:
        return {"ok": False, "error": f"Node not found: {old_id}"}
    if new_id != old_id and new_id in nodes:
        return {"ok": False, "error": f"Node already exists: {new_id}"}
    updated = json.loads(json.dumps(document))
    if new_id != old_id:
        updated["nodes"] = {new_id if key == old_id else key: value for key, value in updated["nodes"].items()}
    updated = _rewrite_node_references(updated, old_id, new_id)
    preview = preview_graph(updated)
    return {**preview, "renamed": {"from": old_id, "to": new_id}}


def duplicate_node(document: dict[str, Any], node_id: str, new_id: str) -> dict[str, Any]:
    nodes = document.get("nodes") or {}
    if node_id not in nodes:
        return {"ok": False, "error": f"Node not found: {node_id}"}
    if new_id in nodes:
        return {"ok": False, "error": f"Node already exists: {new_id}"}
    updated = json.loads(json.dumps(document))
    copy = json.loads(json.dumps(updated["nodes"][node_id]))
    copy["title"] = f"{copy.get('title', node_id)} copy"
    updated["nodes"][new_id] = copy
    preview = preview_graph(updated)
    return {**preview, "ok": True, "editable": True}


def _rewrite_node_references(value: Any, old_id: str, new_id: str, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: _rewrite_node_references(item, old_id, new_id, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_node_references(item, old_id, new_id, key) for item in value]
    if not isinstance(value, str):
        return value
    if key in {"from", "to", "node", "depends_on", "entrypoints"} and value == old_id:
        return new_id
    return value.replace(f"nodes.{old_id}.", f"nodes.{new_id}.")


def _json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found")
    value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("response root is not an object")
    return value


def _change_summary(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    before_nodes, after_nodes = before.get("nodes") or {}, after.get("nodes") or {}
    for node_id in sorted(after_nodes.keys() - before_nodes.keys()):
        changes.append({"operation": "add", "pointer": f"/nodes/{node_id}", "explanation": "Added a workflow node."})
    for node_id in sorted(before_nodes.keys() - after_nodes.keys()):
        changes.append({"operation": "remove", "pointer": f"/nodes/{node_id}", "explanation": "Removed a workflow node."})
    for node_id in sorted(before_nodes.keys() & after_nodes.keys()):
        if before_nodes[node_id] != after_nodes[node_id]:
            changes.append({"operation": "replace", "pointer": f"/nodes/{node_id}", "explanation": "Updated the node contract."})
    if before.get("objective") != after.get("objective"):
        changes.append({"operation": "replace", "pointer": "/objective", "explanation": "Updated the graph objective."})
    return changes


def _trusted_plugin_graph_templates() -> list[dict[str, Any]]:
    """Discover strictly valid graph templates from enabled, reviewed plugin packs."""
    from magent.plugins import list_plugins

    templates: list[dict[str, Any]] = []
    for plugin in list_plugins().get("plugins") or []:
        metadata = plugin.get("metadata") or {}
        trust = str(metadata.get("trust") or "").lower()
        if not plugin.get("enabled") or not plugin.get("valid") or trust not in {"reviewed", "trusted"}:
            continue
        root = Path(str(plugin.get("path") or ""))
        for path in sorted((root / "graphs").glob("*.agraph.*")) if (root / "graphs").is_dir() else []:
            try:
                inspected = inspect_graph(path, strict=True)
            except Exception:
                continue
            if inspected.get("ok"):
                document = inspected["document"]
                templates.append({
                    "id": f"{plugin.get('name')}:{document.get('id')}",
                    "title": document.get("title") or path.stem,
                    "description": document.get("objective") or "Plugin graph template",
                    "source": "plugin",
                    "plugin": plugin.get("name"),
                    "trust": trust,
                    "digest": inspected["digest"],
                    "document": document,
                })
    return templates


def _profile_findings(document: dict[str, Any], project: str | Path, config: Any | None) -> list[dict[str, str]]:
    from magent.agent_profiles.registry import AgentProfileRegistry

    profiles, _warnings = AgentProfileRegistry(project, config).discover()
    findings = []
    for node_id, node in (document.get("nodes") or {}).items():
        name = str(node.get("x-magagent-profile") or "").strip().lstrip("@").lower()
        if name and name not in profiles:
            findings.append({"code": "MAGP001", "severity": "error", "message": f"Agent profile not found: {name}", "pointer": f"/nodes/{node_id}/x-magagent-profile"})
    return findings


def _yaml_text(document: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
