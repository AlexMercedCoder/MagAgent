"""Automated memory hygiene.

`memory quality` reports on the graph; this acts on it. Duplicate facts
accumulate as the same thing gets restated, and `session_summary` nodes are
only interesting while they are recent — without decay a graph grows
monotonically and recall gets noisier over time.

Everything here is dry-run by default: memory is the user's, and pruning it
without being asked is not a decision this should make on its own.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = ["duplicate_groups", "hygiene_report", "stale_nodes", "run_hygiene"]

# Node types that are snapshots of a moment rather than durable knowledge.
DECAYING_TYPES = {"session_summary", "scratch", "observation"}
DEFAULT_TTL_DAYS = 45
DEFAULT_SIMILARITY = 0.86


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _shingles(text: str, size: int = 4) -> set[str]:
    words = _normalise(text).split()
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[index : index + size]) for index in range(len(words) - size + 1)}


def _similarity(left: str, right: str) -> float:
    """Jaccard overlap of word shingles: cheap, and good enough to group restatements."""
    first, second = _shingles(left), _shingles(right)
    if not first or not second:
        return 1.0 if first == second else 0.0
    return len(first & second) / len(first | second)


def duplicate_groups(nodes: list[dict[str, Any]], threshold: float = DEFAULT_SIMILARITY) -> list[dict[str, Any]]:
    """Group nodes that say substantially the same thing."""
    groups: list[dict[str, Any]] = []
    claimed: set[str] = set()

    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or "")
        if not node_id or node_id in claimed:
            continue

        members = []
        for other in nodes[index + 1 :]:
            other_id = str(other.get("id") or "")
            if not other_id or other_id in claimed:
                continue
            if node.get("type") != other.get("type"):
                continue
            score = _similarity(node.get("body", ""), other.get("body", ""))
            if score >= threshold:
                members.append({"id": other_id, "similarity": round(score, 3)})
                claimed.add(other_id)

        if members:
            claimed.add(node_id)
            groups.append(
                {
                    "keep": node_id,
                    "type": node.get("type", ""),
                    "duplicates": members,
                    "preview": _normalise(node.get("body", ""))[:120],
                }
            )

    return groups


def stale_nodes(
    nodes: list[dict[str, Any]],
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    types: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Decaying-type nodes older than the TTL."""
    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    decaying = types or DECAYING_TYPES
    stale = []

    for node in nodes:
        if node.get("type") not in decaying:
            continue
        raw = node.get("updated_at") or node.get("created_at") or ""
        try:
            stamp = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        if stamp < cutoff:
            stale.append(
                {
                    "id": str(node.get("id") or ""),
                    "type": node.get("type", ""),
                    "age_days": (datetime.now(UTC) - stamp).days,
                    "preview": _normalise(node.get("body", ""))[:120],
                }
            )

    return stale


def hygiene_report(
    manager: Any,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    threshold: float = DEFAULT_SIMILARITY,
) -> dict[str, Any]:
    """What hygiene would change, without changing anything."""
    if not getattr(manager, "available", False):
        return {"ok": False, "error": "Memory is not available for this user"}

    try:
        nodes = list(manager.export_json() or [])
    except Exception as error:
        return {"ok": False, "error": f"Could not read the memory graph: {error}"}

    duplicates = duplicate_groups(nodes, threshold=threshold)
    stale = stale_nodes(nodes, ttl_days=ttl_days)

    return {
        "ok": True,
        "nodes": len(nodes),
        "duplicate_groups": duplicates,
        "duplicate_count": sum(len(group["duplicates"]) for group in duplicates),
        "stale": stale,
        "stale_count": len(stale),
        "ttl_days": ttl_days,
        "similarity_threshold": threshold,
    }


def run_hygiene(
    manager: Any,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    threshold: float = DEFAULT_SIMILARITY,
    remove_duplicates: bool = True,
    remove_stale: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    """Apply hygiene. Dry run unless `apply=True`."""
    report = hygiene_report(manager, ttl_days=ttl_days, threshold=threshold)
    if not report.get("ok"):
        return report

    targets: list[str] = []
    if remove_duplicates:
        targets.extend(
            member["id"] for group in report["duplicate_groups"] for member in group["duplicates"]
        )
    if remove_stale:
        targets.extend(item["id"] for item in report["stale"])

    report["targets"] = targets
    report["applied"] = False

    if not apply or not targets:
        return report

    delete = getattr(manager, "delete_node", None)
    if not callable(delete):
        report["error"] = "This memory backend does not support deletion"
        return report

    removed = []
    for node_id in targets:
        try:
            if delete(node_id):
                removed.append(node_id)
        except Exception:
            continue

    report["applied"] = True
    report["removed"] = removed
    report["removed_count"] = len(removed)
    return report
