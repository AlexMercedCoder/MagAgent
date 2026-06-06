"""Context-map and memory-promotion helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from magent.memory import NODE_FACT, NODE_PATTERN, NODE_PROJECT
from magent.records import PromotionCandidateRecord
from magent.workbench import (
    WorkbenchStore,
    command_history,
    list_plans,
    project_command_roles,
    project_doctor,
    workspace_status,
)


def context_map(
    store: WorkbenchStore,
    project: str | Path = ".",
    memory_manager: Any | None = None,
    query: str = "",
) -> dict[str, Any]:
    """Summarize what MagAgent knows about the current project right now."""
    root = Path(project).resolve()
    memory_stats = memory_manager.stats() if memory_manager is not None else {}
    memory_recall = ""
    if memory_manager is not None and query:
        memory_recall = memory_manager.recall(query)
    candidates = promotion_candidates(store, root)
    return {
        "ok": True,
        "project": str(root),
        "workspace": workspace_status(store, root),
        "project_doctor": project_doctor(root, store),
        "command_roles": project_command_roles(root),
        "active_workbench": {
            "tasks": [
                item for item in store.read("tasks", []) if item.get("status", "open") != "done"
            ][:10],
            "plans": list_plans(store)[:10],
            "patches": store.read("patches", [])[-10:],
            "reviews": store.read("reviews", [])[-5:],
            "failed_commands": [
                item for item in command_history(store, root) if item.get("ok") is False
            ][:10],
        },
        "memory": {
            "available": bool(getattr(memory_manager, "available", False)) if memory_manager is not None else False,
            "stats": memory_stats,
            "recall": memory_recall,
        },
        "promotion_candidates": candidates,
    }


def promotion_candidates(
    store: WorkbenchStore,
    project: str | Path = ".",
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return workbench facts that are good candidates for durable memory."""
    root = Path(project).resolve()
    root_slug = _slug(root.name)
    candidates: list[dict[str, Any]] = []

    doctor = project_doctor(root, store)
    roles = project_command_roles(root)
    role_lines = [f"- {name}: `{command}`" for name, command in sorted(roles.items()) if command]
    if role_lines:
        candidates.append(
            _candidate(
                source="project",
                source_id=root_slug,
                title=f"Project command profile for {root.name}",
                node_type=NODE_PROJECT,
                body="\n".join(
                    [
                        f"# Project command profile: {root.name}",
                        "",
                        f"Root: `{root}`",
                        "",
                        "## Commands",
                        *role_lines,
                        "",
                        f"Missing roles: {', '.join(doctor.get('missing', [])) or 'none'}",
                    ]
                ),
                tags=["project", "commands"],
            )
        )

    for item in store.read("tasks", []):
        if item.get("status", "open") == "done":
            continue
        candidates.append(
            _candidate(
                source="task",
                source_id=item.get("id", ""),
                title=item.get("title", "Task"),
                node_type=NODE_FACT,
                body=_frontmatter_body(
                    "Task to remember",
                    {
                        "Title": item.get("title", ""),
                        "Project": item.get("project", str(root)),
                        "Priority": item.get("priority", "normal"),
                        "Status": item.get("status", "open"),
                    },
                ),
                tags=["task"],
            )
        )

    for item in list_plans(store):
        if item.get("status") not in {"draft", "pending", "failed"}:
            continue
        candidates.append(
            _candidate(
                source="plan",
                source_id=item.get("id", ""),
                title=item.get("goal", "Plan"),
                node_type=NODE_PATTERN,
                body=_frontmatter_body(
                    "Implementation plan",
                    {
                        "Goal": item.get("goal", ""),
                        "Status": item.get("status", ""),
                        "Project": item.get("project", str(root)),
                    },
                    item.get("preview") or item.get("plan_markdown", ""),
                ),
                tags=["plan"],
            )
        )

    for item in command_history(store, root):
        if item.get("ok") is not False:
            continue
        candidates.append(
            _candidate(
                source="command",
                source_id=item.get("id", ""),
                title=f"Command failure: {item.get('command', '')}",
                node_type=NODE_PATTERN,
                body=_frontmatter_body(
                    "Command failure pattern",
                    {
                        "Command": item.get("command", ""),
                        "Root": item.get("root", str(root)),
                        "Source": item.get("source", ""),
                        "ReturnCode": item.get("returncode", item.get("exit_code", "")),
                    },
                    item.get("stderr") or item.get("stdout") or item.get("detail", ""),
                ),
                tags=["command", "failure"],
            )
        )

    for item in store.read("reviews", [])[-10:]:
        findings = item.get("findings") or item.get("summary", {}).get("findings") or []
        if not findings:
            continue
        body = ["# Review findings", "", f"Review: `{item.get('id', '')}`", ""]
        for finding in findings[:8]:
            if isinstance(finding, dict):
                body.append(f"- {finding.get('priority', '')} {finding.get('finding') or finding.get('message') or finding}")
            else:
                body.append(f"- {finding}")
        candidates.append(
            _candidate(
                source="review",
                source_id=item.get("id", ""),
                title=f"Review findings {item.get('id', '')}",
                node_type=NODE_PATTERN,
                body="\n".join(body),
                tags=["review"],
            )
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate["id"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped[:limit]


def promote_candidate(
    store: WorkbenchStore,
    memory_manager: Any,
    source: str,
    source_id: str,
    project: str | Path = ".",
) -> dict[str, Any]:
    """Promote one workbench candidate into MagGraph memory."""
    candidates = promotion_candidates(store, project)
    match = next(
        (
            item
            for item in candidates
            if item.get("source") == source and item.get("source_id") == source_id
        ),
        None,
    )
    if not match:
        return {"ok": False, "error": f"Promotion candidate not found: {source}/{source_id}"}
    record = PromotionCandidateRecord.from_mapping(match)
    written = memory_manager.write_memories([record.to_memory_item()], project_slug=_slug(Path(project).resolve().name))
    return {
        "ok": written > 0,
        "written": written,
        "candidate": record.to_memory_item(),
    }


def promote_all_candidates(
    store: WorkbenchStore,
    memory_manager: Any,
    project: str | Path = ".",
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Promote all current candidates into MagGraph memory."""
    candidates = promotion_candidates(store, project, limit=limit)
    memory_items = [
        PromotionCandidateRecord.from_mapping(candidate).to_memory_item()
        for candidate in candidates
    ]
    written = memory_manager.write_memories(memory_items, project_slug=_slug(Path(project).resolve().name))
    return {"ok": written == len(candidates), "written": written, "candidates": candidates}


def _candidate(
    *,
    source: str,
    source_id: str,
    title: str,
    node_type: str,
    body: str,
    tags: list[str],
) -> dict[str, Any]:
    source_id = str(source_id or _slug(title))
    return {
        "id": f"promoted_{source}_{_slug(source_id + '_' + title)}",
        "type": node_type,
        "source": source,
        "source_id": source_id,
        "title": title,
        "body": body.rstrip() + "\n\nPromotedFrom: " + f"{source}/{source_id}\n",
        "tags": tags,
        "links": [],
    }


def _frontmatter_body(title: str, fields: dict[str, Any], details: str = "") -> str:
    lines = [f"# {title}", ""]
    for key, value in fields.items():
        if value not in {None, ""}:
            lines.append(f"{key}: {value}")
    if details:
        lines.extend(["", "## Details", "", str(details).strip()])
    return "\n".join(lines)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return slug[:72] or "item"
