"""Machine-readable Agentic Graph authoring contracts for desktop clients."""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import queue
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from magent.agraph.document import graph_digest, load_graph
from magent.agraph.generate import generate_graph_document
from magent.agraph.plan import resolved_plan
from magent.agraph.validate import validate_graph

CONTRACT_VERSION = "magent.agentic-graph-authoring.v2"
NODE_TYPES = ("task", "decision", "gate", "loop", "map", "subgraph")


def _model_attempt_timeout() -> float:
    try:
        configured = float(os.environ.get("MAGENT_GRAPH_DRAFT_ATTEMPT_TIMEOUT", "120"))
    except ValueError:
        configured = 120.0
    return max(30.0, min(300.0, configured))


MODEL_ATTEMPT_TIMEOUT_SECONDS = _model_attempt_timeout()


async def _bounded_provider_complete(
    provider: Any,
    messages: list[dict[str, str]],
    *,
    timeout: float,
) -> str:
    """Bound providers whose SDK worker threads do not honor asyncio cancellation."""
    results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            value = asyncio.run(provider.complete(messages, temperature=0.1, max_tokens=12000))
            results.put_nowait((True, value))
        except BaseException as exc:  # noqa: BLE001 - forwarded to the authoring loop
            results.put_nowait((False, exc))

    threading.Thread(
        target=invoke,
        name="magent-graph-provider",
        daemon=True,
    ).start()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            ok, value = results.get_nowait()
        except queue.Empty:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError from None
            await asyncio.sleep(min(0.05, remaining))
            continue
        if ok:
            return str(value)
        if isinstance(value, Exception):
            raise value
        raise RuntimeError(f"Planning provider failed: {value}")


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
        base.update(
            {
                "intelligence": {"tier": "standard"},
                "requirements": {
                    "tools": ["file_read"],
                    "permissions": ["fs:read:**"],
                    "workspace": "read_only",
                },
                "constraints": {"max_agent_steps": 16, "max_wall_clock_seconds": 900},
                "failure": {
                    "retry": {"max_attempts": 2, "retry_on": ["transient", "criteria_failed"]},
                    "on_exhausted": "fail",
                },
                "estimate": {"effort": "s", "cost_usd": 0.2},
            }
        )
    elif node_type == "decision":
        base["decision"] = {
            "question": "Which reviewed path should run?",
            "branches": [{"label": "continue", "description": "Continue with the default path."}],
        }
        base["intelligence"] = {"tier": "standard"}
    elif node_type == "gate":
        base["gate"] = {
            "mode": "approve",
            "prompt": "Approve this graph checkpoint?",
            "on_reject": "fail",
        }
    elif node_type in {"loop", "map"}:
        body = {"entrypoints": ["work"], "nodes": {"work": node_template("task", 1)}}
        if node_type == "loop":
            base["loop"] = {"mode": "repeat", "max_iterations": 1, "body": body}
        else:
            base["map"] = {
                "over": "[]",
                "as": "item",
                "max_items": 10,
                "max_parallel": 1,
                "body": body,
            }
    else:
        base["subgraph"] = {
            "inline": {"entrypoints": ["work"], "nodes": {"work": node_template("task", 1)}},
            "inherit_context": False,
        }
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


def preview_graph(
    document: dict[str, Any], *, project: str | Path = ".", config: Any | None = None
) -> dict[str, Any]:
    report = validate_graph(document, strict=True)
    findings = list(report.as_dict().get("findings") or [])
    findings.extend(_profile_findings(document, project, config))
    findings.extend(_tool_findings(document))
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
            return {
                "ok": False,
                "conflict": True,
                "error": "Graph changed on disk",
                "current_digest": current,
            }
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
    return {
        "ok": True,
        "contract": CONTRACT_VERSION,
        "path": str(target),
        "digest": graph_digest(document),
        "document": document,
    }


def generate_draft(goal: str, *, project: str | Path = ".") -> dict[str, Any]:
    document = _capability_aware_baseline(generate_graph_document(goal, project=project), goal)
    return {
        "ok": True,
        "contract": CONTRACT_VERSION,
        "document": document,
        "digest": graph_digest(document),
    }


async def model_graph_draft(
    goal: str,
    *,
    project: str | Path = ".",
    config: Any,
    document: dict[str, Any] | None = None,
    instruction: str = "",
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Ask the configured planning model for a review-only, strictly valid graph proposal."""
    from magent.agraph.mappings import TOOL_NAME_MAP
    from magent.cli.command_context import build_provider_for_role
    from magent.tools.catalog import built_in_tool_definitions

    provider = build_provider_for_role(config, "review")
    schema_path = Path(__file__).parent / "schema" / "agentic-graph-1.0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    baseline = document or generate_graph_document(goal, project=project)
    if document is None:
        baseline = _capability_aware_baseline(baseline, goal)
    concrete_tools = {item["function"]["name"] for item in built_in_tool_definitions()}
    logical_tools = {
        logical: {
            "routes_to": [tool for tool in routed if tool in concrete_tools],
            "required_permissions": _permissions_for_tools(routed),
        }
        for logical, routed in TOOL_NAME_MAP.items()
        if any(tool in concrete_tools for tool in routed)
    }

    def report(
        stage: str,
        message: str,
        *,
        attempt: int = 0,
        finding_count: int = 0,
        details: list[str] | None = None,
    ) -> None:
        if progress is not None:
            progress(
                {
                    "stage": stage,
                    "message": message,
                    "attempt": attempt,
                    "finding_count": finding_count,
                    "details": details or [],
                }
            )

    report("preparing", "Prepared a bounded AGS draft and validation schema.")
    project_root = Path(project).expanduser().resolve()
    prompt = {
        "goal": goal,
        "instruction": instruction
        or "Improve this graph while preserving a bounded, reviewable workflow.",
        "project": str(project_root),
        "current_graph": baseline,
        "allowed_node_types": list(NODE_TYPES),
        "allowed_logical_tools": logical_tools,
        "capability_rules": [
            "Use only names from allowed_logical_tools in requirements.tools; never invent a tool name.",
            "Declare every capability the node may call and its listed required_permissions.",
            "External research normally needs both web_search and web_fetch plus a net: permission.",
            "Creating or editing project files needs file_write plus fs:write:**.",
            "Running build, test, or shell commands needs shell_exec plus shell:exec:*.",
            "Prefer the narrowest sufficient set of tools and permissions for each node.",
        ],
        "schema": schema,
    }
    messages = [
        {
            "role": "system",
            "content": "Return only one JSON object conforming to the supplied AGS 1.0 schema. Do not use markdown fences. Use only the supplied canonical logical tool names, declare every capability needed to complete each card, and pair it with the required permission. Never widen permissions beyond the task.",
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    errors: list[str] = []
    for _attempt in range(3):
        attempt = _attempt + 1
        report("requesting", "The planning model is drafting the graph.", attempt=attempt)
        try:
            raw = await _bounded_provider_complete(
                provider,
                messages,
                timeout=MODEL_ATTEMPT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            message = (
                f"The planning model did not answer within "
                f"{int(MODEL_ATTEMPT_TIMEOUT_SECONDS)} seconds."
            )
            errors.append(message)
            report("timeout", message, attempt=attempt)
            break
        report("received", "Received a proposal; parsing and validating it now.", attempt=attempt)
        try:
            proposed = _json_object(raw)
        except ValueError as exc:
            errors.append(str(exc))
            report(
                "repairing",
                "The response was incomplete JSON; requesting a corrected proposal.",
                attempt=attempt,
            )
            messages.append(
                {
                    "role": "user",
                    "content": f"The response was not a JSON object: {exc}. Return a complete corrected graph JSON object only.",
                }
            )
            continue
        preview = preview_graph(proposed, project=project_root, config=config)
        if preview["ok"]:
            report(
                "validated", "The generated graph passed strict AGS validation.", attempt=attempt
            )
            return {
                **preview,
                "proposal": True,
                "model": getattr(provider, "display_name", "planning model"),
                "profile": "planning-role:review",
                "changes": _change_summary(baseline, proposed),
            }
        findings = preview.get("validation", {}).get("findings", [])
        finding_messages = [str(item.get("message") or "").strip() for item in findings[:12]]
        finding_messages = [message for message in finding_messages if message]
        errors.append("; ".join(finding_messages))
        report(
            "repairing",
            f"Validation found {len(findings)} issue{'s' if len(findings) != 1 else ''}; requesting a repair.",
            attempt=attempt,
            finding_count=len(findings),
            details=finding_messages[:3],
        )
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": "Repair these validation findings and return the entire corrected JSON object only: "
                + errors[-1],
            }
        )
    fallback = preview_graph(baseline, project=project_root, config=config)
    if fallback["ok"]:
        reason = errors[-1] if errors else "The planning model did not return a validated proposal."
        report(
            "fallback",
            "Using the validated capability-aware draft because the model proposal was unavailable.",
            attempt=min(3, max(1, len(errors))),
            details=[reason[:500]],
        )
        return {
            **fallback,
            "proposal": True,
            "fallback": True,
            "fallback_reason": reason,
            "model": getattr(provider, "display_name", "planning model"),
            "profile": "planning-role:review",
            "changes": _change_summary(baseline, baseline),
            "model_findings": errors,
        }
    report("failed", "The proposal and its safe fallback did not pass validation.", attempt=3)
    return {
        "ok": False,
        "error": _model_failure_message(errors, fallback),
        "attempts": 3,
        "findings": errors,
    }


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
        updated["nodes"] = {
            new_id if key == old_id else key: value for key, value in updated["nodes"].items()
        }
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
        return {
            name: _rewrite_node_references(item, old_id, new_id, name)
            for name, item in value.items()
        }
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
        changes.append(
            {
                "operation": "add",
                "pointer": f"/nodes/{node_id}",
                "explanation": "Added a workflow node.",
            }
        )
    for node_id in sorted(before_nodes.keys() - after_nodes.keys()):
        changes.append(
            {
                "operation": "remove",
                "pointer": f"/nodes/{node_id}",
                "explanation": "Removed a workflow node.",
            }
        )
    for node_id in sorted(before_nodes.keys() & after_nodes.keys()):
        if before_nodes[node_id] != after_nodes[node_id]:
            changes.append(
                {
                    "operation": "replace",
                    "pointer": f"/nodes/{node_id}",
                    "explanation": "Updated the node contract.",
                }
            )
    if before.get("objective") != after.get("objective"):
        changes.append(
            {
                "operation": "replace",
                "pointer": "/objective",
                "explanation": "Updated the graph objective.",
            }
        )
    return changes


def _trusted_plugin_graph_templates() -> list[dict[str, Any]]:
    """Discover strictly valid graph templates from enabled, reviewed plugin packs."""
    from magent.plugins import list_plugins

    templates: list[dict[str, Any]] = []
    for plugin in list_plugins().get("plugins") or []:
        metadata = plugin.get("metadata") or {}
        trust = str(metadata.get("trust") or "").lower()
        if (
            not plugin.get("enabled")
            or not plugin.get("valid")
            or trust not in {"reviewed", "trusted"}
        ):
            continue
        root = Path(str(plugin.get("path") or ""))
        for path in (
            sorted((root / "graphs").glob("*.agraph.*")) if (root / "graphs").is_dir() else []
        ):
            try:
                inspected = inspect_graph(path, strict=True)
            except Exception:
                continue
            if inspected.get("ok"):
                document = inspected["document"]
                templates.append(
                    {
                        "id": f"{plugin.get('name')}:{document.get('id')}",
                        "title": document.get("title") or path.stem,
                        "description": document.get("objective") or "Plugin graph template",
                        "source": "plugin",
                        "plugin": plugin.get("name"),
                        "trust": trust,
                        "digest": inspected["digest"],
                        "document": document,
                    }
                )
    return templates


def _profile_findings(
    document: dict[str, Any], project: str | Path, config: Any | None
) -> list[dict[str, str]]:
    from magent.agent_profiles.registry import AgentProfileRegistry

    profiles, _warnings = AgentProfileRegistry(project, config).discover()
    findings = []
    for node_id, node in (document.get("nodes") or {}).items():
        name = str(node.get("x-magagent-profile") or "").strip().lstrip("@").lower()
        if name and name not in profiles:
            findings.append(
                {
                    "code": "MAGP001",
                    "severity": "error",
                    "message": f"Agent profile not found: {name}",
                    "pointer": f"/nodes/{node_id}/x-magagent-profile",
                }
            )
    return findings


def _capability_aware_baseline(document: dict[str, Any], goal: str) -> dict[str, Any]:
    """Adapt the safe generated skeleton to obvious goal capabilities before model review."""
    updated = json.loads(json.dumps(document))
    text = goal.lower()
    nodes = updated.get("nodes") or {}
    inspect = nodes.get("inspect")
    if inspect and any(
        token in text
        for token in ("research", "history", "authoritative source", "web", "internet")
    ):
        inspect["title"] = "Research authoritative sources"
        inspect["description"] = (
            f"Research this objective using authoritative external sources: {goal.strip()}. "
            "Use web_search to locate relevant sources and web_fetch to read them. Emit a "
            "concise synthesis with source URLs and the facts the next card should use. Do not "
            "edit project files."
        )
        inspect["requirements"] = {
            "tools": ["file_read", "file_search", "web_search", "web_fetch"],
            "permissions": ["fs:read:**", "net:fetch:https://**"],
            "workspace": "read_only",
        }
        inspect.setdefault("intelligence", {})["hints"] = [
            "tool_use_heavy",
            "long_context",
            "precision_critical",
        ]
    implement = nodes.get("implement")
    if implement and any(
        token in text
        for token in (
            "create",
            "build",
            "implement",
            "website",
            "html",
            "css",
            "javascript",
            " js ",
        )
    ):
        implement["requirements"] = {
            "tools": ["file_read", "file_search", "file_write", "shell_exec"],
            "permissions": ["fs:read:**", "fs:write:**", "shell:exec:*"],
            "workspace": "read_write",
        }
    return updated


def _model_failure_message(errors: list[str], fallback: dict[str, Any]) -> str:
    details = [item for item in errors if item]
    fallback_errors = [
        str(item.get("message") or "").strip()
        for item in (fallback.get("validation") or {}).get("findings") or []
        if item.get("severity") == "error"
    ]
    details.extend(item for item in fallback_errors if item)
    if not details:
        return "The model proposal and safe fallback did not pass strict validation."
    return "Graph generation could not produce a runnable draft: " + " | ".join(details[-4:])


def _permissions_for_tools(tools: tuple[str, ...] | list[str]) -> list[str]:
    """Describe the minimum AGS permission families needed by concrete tools."""
    required: list[str] = []
    names = set(tools)
    if names & {
        "read_file",
        "read_file_range",
        "outline_file",
        "list_dir",
        "search_codebase",
        "diff_files",
    }:
        required.append("fs:read:**")
    if names & {"write_file", "edit_file", "apply_patch", "delete_file"}:
        required.append("fs:write:**")
    if "run_shell" in names:
        required.append("shell:exec:*")
    if any(name.startswith(("web_", "http_", "browser_")) for name in names):
        required.append("net:fetch:https://**")
    return required


def _tool_findings(document: dict[str, Any]) -> list[dict[str, str]]:
    """Reject unavailable tool names and capability/permission mismatches before a run."""
    from magent.agraph.mappings import TOOL_NAME_MAP, tool_requirement, tools_for_requirement
    from magent.tools.catalog import built_in_tool_definitions

    available = {item["function"]["name"] for item in built_in_tool_definitions()}
    canonical = sorted(TOOL_NAME_MAP)
    findings: list[dict[str, str]] = []
    for node_id, node in (document.get("nodes") or {}).items():
        requirements = node.get("requirements") or {}
        permissions = [str(item) for item in requirements.get("permissions") or []]
        for index, item in enumerate(requirements.get("tools") or []):
            name, optional, _alternatives = tool_requirement(item)
            routed = tools_for_requirement(item)
            pointer = f"/nodes/{node_id}/requirements/tools/{index}"
            if not optional and not any(tool in available for tool in routed):
                suggestion = difflib.get_close_matches(name, canonical, n=1, cutoff=0.45)
                hint = f" Did you mean {suggestion[0]!r}?" if suggestion else ""
                findings.append(
                    {
                        "code": "MAGT001",
                        "severity": "error",
                        "message": f"Tool capability {name!r} is not available in MagAgent.{hint} Choose a canonical logical tool from the authoring catalog.",
                        "pointer": pointer,
                    }
                )
                continue
            needed = _permissions_for_tools([tool for tool in routed if tool in available])
            for permission in needed:
                family = permission.split(":", 1)[0] + ":"
                if not any(value.startswith(family) for value in permissions):
                    findings.append(
                        {
                            "code": "MAGT002",
                            "severity": "error",
                            "message": f"Tool capability {name!r} also needs a {family.rstrip(':')!r} permission. Add {permission!r} or remove the capability.",
                            "pointer": f"/nodes/{node_id}/requirements/permissions",
                        }
                    )
    return findings


def _yaml_text(document: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
