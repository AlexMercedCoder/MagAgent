"""Read-only memory browsing for the Web UI.

Memory shapes every reply, and the browser could only see the promotion inbox:
what the agent already believed was invisible.
"""

from __future__ import annotations

from typing import Any

import pytest

from magent import web_memory


class FakeManager:
    """A memory graph without maggraph installed.

    The real manager needs the `maggraph` index, which is not a test
    dependency; these cover the adapter's own decisions.
    """

    def __init__(self, nodes: dict[str, dict[str, Any]] | None = None, available: bool = True):
        self._nodes = nodes or {}
        self.available = available
        self.searched: list[tuple[str, int, str]] = []

    def list_nodes(self) -> list[str]:
        return list(self._nodes)

    def read_node(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)

    def stats(self) -> dict[str, Any]:
        return {"nodes": len(self._nodes), "edges_total": 3, "disk_bytes": 2048}

    def quality_report(self) -> dict[str, Any]:
        return {"ok": True, "nodes": len(self._nodes), "duplicates": [], "suppressed": []}

    def search(self, query: str, max_results: int = 10, mode: str = "keyword") -> list[dict]:
        self.searched.append((query, max_results, mode))
        return [node for node in self._nodes.values() if query in str(node.get("body", ""))]

    def backlinks(self, node_id: str) -> list[str]:
        return [other for other, node in self._nodes.items() if node_id in node.get("links", [])]

    def write_memories(self, records: list[dict[str, Any]]) -> int:
        for record in records:
            self._nodes[record["id"]] = {**record, "path": f"{record['id']}.md"}
        return len(records)

    def update_node(self, node_id: str, *, body: str, links: list[str]) -> dict[str, Any]:
        if node_id not in self._nodes:
            return {"ok": False, "error": "missing"}
        self._nodes[node_id].update(body=body, links=links)
        return {"ok": True}

    def delete_node(self, node_id: str) -> bool:
        return self._nodes.pop(node_id, None) is not None


def _node(node_id: str, body: str = "a note", links: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "fact",
        "body": body,
        "links": links or [],
        "path": f"{node_id}.md",
    }


@pytest.fixture
def graph(monkeypatch) -> FakeManager:
    manager = FakeManager(
        {
            "alpha": _node("alpha", "the user prefers tabs", links=["beta"]),
            "beta": _node("beta", "the project ships on Fridays"),
        }
    )
    monkeypatch.setattr(web_memory, "_manager", lambda _username: manager)
    return manager


# --- overview ----------------------------------------------------------------


def test_overview_reports_the_graph_and_its_quality(graph: FakeManager) -> None:
    payload = web_memory.overview("alex")

    assert payload["ok"] is True
    assert payload["stats"]["nodes"] == 2
    assert payload["quality"]["ok"] is True
    assert {row["id"] for row in payload["nodes"]} == {"alpha", "beta"}


def test_overview_says_so_when_no_graph_exists(monkeypatch) -> None:
    monkeypatch.setattr(web_memory, "_manager", lambda _u: FakeManager(available=False))
    payload = web_memory.overview("alex")

    assert payload["ok"] is True
    assert payload["available"] is False
    # An empty list with no explanation reads as a broken page.
    assert "No memory graph" in payload["note"]


def test_overview_caps_the_roster_and_says_it_did(monkeypatch) -> None:
    """Reading every node is fine for a personal graph and ruinous for a large one."""
    many = {f"n{index}": _node(f"n{index}") for index in range(web_memory.MAX_LISTED + 25)}
    monkeypatch.setattr(web_memory, "_manager", lambda _u: FakeManager(many))

    payload = web_memory.overview("alex")
    assert len(payload["nodes"]) == web_memory.MAX_LISTED
    assert payload["total"] == web_memory.MAX_LISTED + 25
    assert payload["truncated"] is True
    assert str(web_memory.MAX_LISTED) in payload["note"]


def test_overview_needs_a_username(graph: FakeManager) -> None:
    assert web_memory.overview("")["ok"] is False


def test_overview_reports_a_broken_graph_instead_of_raising(monkeypatch) -> None:
    class Broken(FakeManager):
        def list_nodes(self) -> list[str]:
            raise RuntimeError("index is corrupt")

    monkeypatch.setattr(web_memory, "_manager", lambda _u: Broken())
    payload = web_memory.overview("alex")

    assert payload["ok"] is False
    assert "corrupt" in payload["error"]


# --- search ------------------------------------------------------------------


def test_search_returns_matching_notes(graph: FakeManager) -> None:
    payload = web_memory.search("alex", "tabs")

    assert payload["ok"] is True
    assert [row["id"] for row in payload["results"]] == ["alpha"]


def test_an_empty_query_searches_nothing(graph: FakeManager) -> None:
    payload = web_memory.search("alex", "   ")

    assert payload["results"] == []
    # It must not reach the index at all, or every keystroke costs a scan.
    assert graph.searched == []


def test_search_is_bounded(graph: FakeManager) -> None:
    web_memory.search("alex", "the", limit=10_000)
    assert graph.searched[-1][1] == web_memory.MAX_RESULTS


@pytest.mark.parametrize("mode", ["keyword", "semantic", "hybrid"])
def test_search_passes_the_chosen_mode_through(graph: FakeManager, mode: str) -> None:
    web_memory.search("alex", "the", mode=mode)
    assert graph.searched[-1][2] == mode


def test_an_unknown_mode_falls_back_to_keyword(graph: FakeManager) -> None:
    """Semantic modes need an embedding index that may not exist."""
    payload = web_memory.search("alex", "the", mode="telepathy")

    assert payload["mode"] == "keyword"
    assert graph.searched[-1][2] == "keyword"


def test_search_reports_a_broken_index_instead_of_raising(monkeypatch) -> None:
    class Broken(FakeManager):
        def search(self, *_args, **_kwargs):
            raise RuntimeError("embedding store missing")

    monkeypatch.setattr(web_memory, "_manager", lambda _u: Broken({"a": _node("a")}))
    payload = web_memory.search("alex", "anything")

    assert payload["ok"] is False
    assert "embedding store" in payload["error"]


# --- node --------------------------------------------------------------------


def test_a_node_carries_its_links_in_both_directions(graph: FakeManager) -> None:
    """Backlinks are the useful direction when asking why the agent believes something."""
    payload = web_memory.node("alex", "beta")

    assert payload["ok"] is True
    assert payload["links"] == []
    assert payload["backlinks"] == ["alpha"]


def test_a_missing_node_is_named_not_crashed(graph: FakeManager) -> None:
    payload = web_memory.node("alex", "nonesuch")

    assert payload["ok"] is False
    assert "nonesuch" in payload["error"]


def test_an_empty_node_id_is_refused(graph: FakeManager) -> None:
    assert web_memory.node("alex", "  ")["ok"] is False


def test_a_long_note_is_truncated_and_says_so(monkeypatch) -> None:
    """A browser should never be handed an unbounded note."""
    long_body = "x" * (web_memory.MAX_BODY_CHARS + 500)
    monkeypatch.setattr(
        web_memory, "_manager", lambda _u: FakeManager({"big": _node("big", long_body)})
    )
    payload = web_memory.node("alex", "big")

    assert len(payload["body"]) == web_memory.MAX_BODY_CHARS
    assert payload["truncated"] is True


def test_a_short_note_is_not_marked_truncated(graph: FakeManager) -> None:
    assert web_memory.node("alex", "alpha")["truncated"] is False


def test_node_needs_a_username(graph: FakeManager) -> None:
    assert web_memory.node("", "alpha")["ok"] is False


def test_memory_nodes_can_be_created_updated_and_deleted(graph: FakeManager) -> None:
    created = web_memory.create(
        "alex", {"id": "gamma", "type": "preference", "body": "Use tabs", "links": ["alpha"]}
    )
    assert created["body"] == "Use tabs"

    updated = web_memory.update("alex", {"id": "gamma", "body": "Use spaces", "links": []})
    assert updated["body"] == "Use spaces"

    assert web_memory.delete("alex", "gamma")["ok"] is True
    assert web_memory.node("alex", "gamma")["ok"] is False


def test_memory_create_rejects_duplicates_and_incomplete_input(graph: FakeManager) -> None:
    assert web_memory.create("alex", {"id": "alpha", "body": "duplicate"})["ok"] is False
    assert web_memory.create("alex", {"id": "new", "body": ""})["ok"] is False
