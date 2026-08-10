"""Deterministic static execution plans for AGS documents."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from magent.agraph.document import GraphDocument, load_graph
from magent.agraph.validate import validate_graph


@dataclass(frozen=True)
class GraphPlan:
    graph_id: str
    graph_digest: str
    order: tuple[str, ...]
    parallel_groups: tuple[tuple[str, ...], ...]
    gates: tuple[str, ...]
    tier_histogram: dict[str, int]
    projected_cost_usd: float
    worst_case_node_executions: int
    max_parallel_nodes: int
    nodes: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "graph_id": self.graph_id,
            "graph_digest": self.graph_digest,
            "order": list(self.order),
            "parallel_groups": [list(group) for group in self.parallel_groups],
            "gates": list(self.gates),
            "tier_histogram": self.tier_histogram,
            "projected_cost_usd": self.projected_cost_usd,
            "worst_case_node_executions": self.worst_case_node_executions,
            "max_parallel_nodes": self.max_parallel_nodes,
            "nodes": list(self.nodes),
        }


def effective_edges(document: dict[str, Any]) -> list[tuple[str, str, str, str | None]]:
    edges: list[tuple[str, str, str, str | None]] = []
    for node_id, node in (document.get("nodes") or {}).items():
        edges.extend((dep, node_id, "sequence", None) for dep in node.get("depends_on") or [])
    edges.extend(
        (str(edge["from"]), str(edge["to"]), str(edge.get("kind", "sequence")), edge.get("when"))
        for edge in document.get("edges") or []
        if edge.get("from") and edge.get("to")
    )
    return list(dict.fromkeys(edges))


def topological_order(document: dict[str, Any]) -> tuple[str, ...]:
    nodes = list((document.get("nodes") or {}).keys())
    position = {node: index for index, node in enumerate(nodes)}
    incoming = dict.fromkeys(nodes, 0)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for source, target, _kind, _when in effective_edges(document):
        if source in incoming and target in incoming:
            incoming[target] += 1
            outgoing[source].append(target)
    ready = sorted((node for node in nodes if incoming[node] == 0), key=position.get)
    result: list[str] = []
    while ready:
        node = ready.pop(0)
        result.append(node)
        for target in outgoing[node]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort(key=position.get)
    return tuple(result)


def plan_graph(source: str | dict[str, Any] | GraphDocument) -> GraphPlan:
    document = source if isinstance(source, GraphDocument) else load_graph(source)
    report = validate_graph(document)
    if not report.ok:
        summary = "; ".join(f"{item.code}: {item.message}" for item in report.errors[:5])
        raise ValueError(f"Invalid Agentic Graph: {summary}")
    data = document.data
    order = topological_order(data)
    levels: dict[str, int] = {}
    for node_id in order:
        parents = [source for source, target, _kind, _when in effective_edges(data) if target == node_id]
        levels[node_id] = max((levels[parent] + 1 for parent in parents), default=0)
    groups: dict[int, list[str]] = defaultdict(list)
    for node_id in order:
        groups[levels[node_id]].append(node_id)
    nodes = data.get("nodes") or {}
    tiers = Counter(str((node.get("intelligence") or {}).get("tier", "standard")) for node in nodes.values() if node.get("type", "task") != "gate")
    cost = sum(float((node.get("estimate") or {}).get("cost_usd", 0) or 0) for node in nodes.values())
    executions = sum(_node_execution_bound(node) for node in nodes.values())
    configured_parallel = int((data.get("constraints") or {}).get("max_parallel_nodes", 1) or 1)
    rows = tuple(
        {
            "id": node_id,
            "type": nodes[node_id].get("type", "task"),
            "title": nodes[node_id].get("title", node_id),
            "tier": (nodes[node_id].get("intelligence") or {}).get("tier", "none"),
            "estimate": nodes[node_id].get("estimate") or {},
            "level": levels[node_id],
        }
        for node_id in order
    )
    return GraphPlan(
        graph_id=document.graph_id,
        graph_digest=document.digest,
        order=order,
        parallel_groups=tuple(tuple(groups[level]) for level in sorted(groups)),
        gates=tuple(node_id for node_id in order if nodes[node_id].get("type") == "gate"),
        tier_histogram=dict(tiers),
        projected_cost_usd=round(cost, 6),
        worst_case_node_executions=executions,
        max_parallel_nodes=max(1, configured_parallel),
        nodes=rows,
    )


def _node_execution_bound(node: dict[str, Any]) -> int:
    attempts = int((((node.get("failure") or {}).get("retry") or {}).get("max_attempts", 1)) or 1)
    node_type = node.get("type", "task")
    multiplier = 1
    if node_type == "loop":
        multiplier = int((node.get("loop") or {}).get("max_iterations", 1) or 1)
    elif node_type == "map":
        multiplier = int((node.get("map") or {}).get("max_items", 1) or 1)
    return max(1, attempts * multiplier)
