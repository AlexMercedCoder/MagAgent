"""Read-only memory browsing for the local Web UI.

MagAgent's memory is a linked graph of notes the agent has written about the
user and their projects, and it shaped every reply. The browser could only see
the promotion inbox, so the memory that was already in force was invisible:
there was no way to ask what the agent believed, or where a belief came from.

Everything here reads. Promotion still goes through `/api/memory/promote`, and
editing, merging, and deletion stay in the CLI, where the destructive commands
already have their confirmations.
"""

from __future__ import annotations

from typing import Any

# A memory graph can hold thousands of nodes, and a browser only shows a window.
MAX_RESULTS = 100
MAX_BODY_CHARS = 4000
# Reading every node to list them is fine for a personal graph and ruinous for
# a large one, so the roster is capped and reports when it was cut.
MAX_LISTED = 300


def _manager(username: str) -> Any:
    from magent.config import user_memory_dir
    from magent.memory import MemoryManager

    return MemoryManager(user_memory_dir(username), username=username)


def _summarise(node: dict[str, Any]) -> dict[str, Any]:
    body = str(node.get("body") or "")
    return {
        "id": str(node.get("id") or ""),
        "type": str(node.get("type") or node.get("node_type") or ""),
        "excerpt": body[:280],
        "links": list(node.get("links") or [])[:20],
        "path": str(node.get("path") or ""),
    }


def overview(username: str) -> dict[str, Any]:
    """What is in memory, and what looks wrong with it."""
    if not username:
        return {"ok": False, "error": "username unavailable"}

    manager = _manager(username)
    if not manager.available:
        return {
            "ok": True,
            "available": False,
            "note": (
                "No memory graph exists yet. It is written as the agent learns "
                "things worth keeping."
            ),
            "stats": {},
            "quality": {},
            "nodes": [],
        }

    try:
        listed = list(manager.list_nodes())
    except Exception as error:  # noqa: BLE001 - reported, never raised
        return {"ok": False, "error": str(error)}

    truncated = len(listed) > MAX_LISTED
    rows = []
    for node_id in listed[:MAX_LISTED]:
        node = manager.read_node(node_id)
        if node:
            rows.append(_summarise(node))

    return {
        "ok": True,
        "available": True,
        "stats": manager.stats(),
        "quality": manager.quality_report(),
        "nodes": rows,
        "total": len(listed),
        "truncated": truncated,
        "note": (
            f"Showing the first {MAX_LISTED} of {len(listed)} nodes. Use search to find the rest."
            if truncated
            else ""
        ),
    }


def search(username: str, query: str, *, mode: str = "keyword", limit: int = 20) -> dict[str, Any]:
    """Search memory the same way the agent's own recall does."""
    if not username:
        return {"ok": False, "error": "username unavailable"}
    query = (query or "").strip()
    if not query:
        return {"ok": True, "query": "", "results": [], "mode": mode}

    # `semantic` and `hybrid` need an embedding index that may not exist; the
    # manager already falls back to keyword, so an unknown mode is not an error.
    if mode not in {"keyword", "semantic", "hybrid"}:
        mode = "keyword"

    manager = _manager(username)
    if not manager.available:
        return {"ok": True, "query": query, "mode": mode, "results": [], "available": False}

    bounded = max(1, min(int(limit or 20), MAX_RESULTS))
    try:
        found = manager.search(query, max_results=bounded, mode=mode)
    except Exception as error:  # noqa: BLE001 - reported, never raised
        return {"ok": False, "error": str(error), "query": query}

    return {
        "ok": True,
        "query": query,
        "mode": mode,
        "results": [_summarise(dict(item)) for item in found],
    }


def node(username: str, node_id: str) -> dict[str, Any]:
    """One memory node in full, with what links to it and what it links out to."""
    if not username:
        return {"ok": False, "error": "username unavailable"}
    node_id = (node_id or "").strip()
    if not node_id:
        return {"ok": False, "error": "A node id is required."}

    manager = _manager(username)
    found = manager.read_node(node_id) if manager.available else None
    if not found:
        return {"ok": False, "error": f"No memory node called {node_id}."}

    body = str(found.get("body") or "")
    return {
        "ok": True,
        "id": str(found.get("id") or node_id),
        "type": str(found.get("type") or ""),
        "path": str(found.get("path") or ""),
        "body": body[:MAX_BODY_CHARS],
        "truncated": len(body) > MAX_BODY_CHARS,
        "links": list(found.get("links") or []),
        # Backlinks are the useful direction when asking why the agent believes
        # something: they show what referred to this note.
        "backlinks": list(manager.backlinks(node_id)),
    }
