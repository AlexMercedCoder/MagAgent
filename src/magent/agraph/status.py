"""Durable graph-run status snapshots for CLI and desktop reconnection."""

from __future__ import annotations

from typing import Any

from magent.agraph.events import GRAPH_STATUS_SCHEMA_VERSION
from magent.agraph.schedule import blocking_reasons
from magent.task_runtime import TaskRuntime
from magent.workbench_store import WorkbenchStore


def graph_status(store: WorkbenchStore, run_id: str, *, event_limit: int = 500) -> dict[str, Any] | None:
    record = next((item for item in reversed(store.read("graph_runs", [])) if item.get("run_id") == run_id), None)
    if not record:
        return None
    runtime = TaskRuntime(store)
    root_id = str((record.get("metadata") or {}).get("execution_task_id") or "")
    root = runtime.get(root_id) if root_id else None
    if root is None:
        root = next((task for task in runtime.list_tasks(limit=1000) if task.get("kind") == "agentic_graph" and (task.get("metadata") or {}).get("run_id") == run_id), None)
        root_id = str((root or {}).get("id") or "")
    children = runtime.list_tasks(parent_task_id=root_id, limit=1000) if root_id else []
    child_by_scope = {str((task.get("metadata") or {}).get("scope_path") or (task.get("metadata") or {}).get("graph_node_id") or (task.get("metadata") or {}).get("node_id") or ""): task for task in children}
    node_records = {str(item.get("scope_path") or item.get("node_id")): item for item in record.get("nodes") or []}
    document = (record.get("metadata") or {}).get("graph_snapshot") or {}
    statuses = {node_id: "pending" for node_id in document.get("nodes") or {}}
    scope: dict[str, Any] = {"nodes": {}, "_statuses": statuses}
    for scope_path, item in node_records.items():
        if "." not in scope_path and "[" not in scope_path:
            statuses[scope_path] = str(item.get("status") or "pending")
            scope["nodes"][scope_path] = {"status": statuses[scope_path], "outputs": item.get("outputs") or {}}
    nodes = []
    for node_id, definition in (document.get("nodes") or {}).items():
        record_item = node_records.get(node_id) or {}
        task = child_by_scope.get(node_id)
        state = str((task or {}).get("state") or record_item.get("status") or "pending")
        blocked = blocking_reasons(document, node_id, statuses, scope) if state in {"pending", "ready", "queued", "waiting", "blocked"} else []
        nodes.append({
            "node_id": node_id,
            "title": str(definition.get("title") or node_id),
            "profile": str(definition.get("x-magagent-profile") or ""),
            "dependencies": list(definition.get("depends_on") or []),
            "state": state,
            "summary": str((task or {}).get("final_audit", {}).get("summary") or record_item.get("summary") or ""),
            "error_code": str((task or {}).get("final_audit", {}).get("error_code") or record_item.get("error_code") or ""),
            "error": str((task or {}).get("final_audit", {}).get("error") or record_item.get("error") or ""),
            "files_changed": list((task or {}).get("files_changed") or record_item.get("files_changed") or []),
            "blocked_by": blocked or list((task or {}).get("metadata", {}).get("blocked_by") or record_item.get("blocked_by") or []),
            "task": task,
            "record": record_item,
        })
    return {
        "ok": True,
        "schema_version": GRAPH_STATUS_SCHEMA_VERSION,
        "run_id": run_id,
        "state": str((root or {}).get("state") or record.get("status") or ""),
        "summary": record.get("summary") or (root or {}).get("final_audit") or {},
        "run": record,
        "task": root,
        "nodes": nodes,
        "events": runtime.events(root_id, limit=event_limit) if root_id else [],
    }
