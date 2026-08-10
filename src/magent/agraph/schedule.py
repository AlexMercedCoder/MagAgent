"""Deterministic AGS edge activation and readiness rules."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from magent.agraph.expressions import AgxEvaluationError, evaluate_expression
from magent.agraph.plan import effective_edges, topological_order

TERMINAL = {"succeeded", "failed", "skipped", "cancelled", "blocked"}


def edge_table(document: dict[str, Any], statuses: dict[str, str], scope: dict[str, Any]) -> list[dict[str, Any]]:
    table = []
    for source, target, kind, when in effective_edges(document):
        active: bool | None = None
        error = ""
        if statuses.get(source) in TERMINAL:
            try:
                if kind == "on_failure":
                    active = statuses.get(source) == "failed" and (not when or bool(evaluate_expression(str(when), scope)))
                elif kind == "conditional":
                    active = bool(evaluate_expression(str(when), scope))
                else:
                    active = statuses.get(source) == "succeeded" and (not when or bool(evaluate_expression(str(when), scope)))
            except AgxEvaluationError as exc:
                active = False
                error = str(exc)
        table.append({"from": source, "to": target, "kind": kind, "when": when, "active": active, "error": error})
    return table


def ready_nodes(document: dict[str, Any], statuses: dict[str, str], scope: dict[str, Any]) -> list[str]:
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edge_table(document, statuses, scope):
        incoming[edge["to"]].append(edge)
    entries = set(document.get("entrypoints") or [])
    ready = []
    nodes = document.get("nodes") or {}
    for node_id in topological_order(document):
        if statuses.get(node_id) != "pending":
            continue
        node = nodes[node_id]
        edges = incoming[node_id]
        if node_id in entries and not edges:
            ready.append(node_id)
            continue
        if not edges or any(edge["active"] is None for edge in edges):
            continue
        active = sum(edge["active"] is True for edge in edges)
        join = node.get("join", "all")
        if (join == "all" and active == len(edges)) or (join == "any" and active >= 1) or (join == "n_of" and active >= int(node.get("join_count", 1))):
            ready.append(node_id)
    return ready


def propagate_skips(document: dict[str, Any], statuses: dict[str, str], scope: dict[str, Any]) -> list[str]:
    skipped = []
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edge_table(document, statuses, scope):
        incoming[edge["to"]].append(edge)
    entries = set(document.get("entrypoints") or [])
    for node_id in topological_order(document):
        if statuses.get(node_id) != "pending" or node_id in entries:
            continue
        edges = incoming[node_id]
        if edges and all(edge["active"] is not None for edge in edges) and not any(edge["active"] for edge in edges):
            statuses[node_id] = "skipped"
            skipped.append(node_id)
    return skipped
