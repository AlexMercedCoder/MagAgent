"""Tests for MagGraph-backed memory behavior."""

from dataclasses import dataclass
from pathlib import Path

from magent.memory import MemoryManager


@dataclass
class FakeNode:
    id: str
    node_type: str
    body: str
    links: list[str]
    relative_path: str = ""


class FakeIndex:
    def __init__(self, nodes: dict[str, FakeNode]):
        self.nodes = nodes
        self.updated: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.created_memory: list[tuple[str, str, str, list[str]]] = []
        self.created_contexts: list[dict[str, object]] = []
        self.updated_files: list[str] = []
        self.suppressed: list[tuple[str, str | None]] = []
        self.unsuppressed: list[str] = []
        self.merged: list[tuple[str, str]] = []

    def list_nodes(self) -> list[str]:
        return list(self.nodes)

    def read_node(self, node_id: str) -> FakeNode:
        return self.nodes[node_id]

    def update_node(self, node_id: str, body: str) -> None:
        self.updated.append((node_id, body))
        node = self.nodes[node_id]
        self.nodes[node_id] = FakeNode(
            id=node.id,
            node_type=node.node_type,
            body=body,
            links=node.links,
            relative_path=node.relative_path,
        )

    def delete_node(self, node_id: str) -> None:
        self.deleted.append(node_id)
        del self.nodes[node_id]

    def search(self, query: str = "", include_suppressed: bool = False, limit: int = 50, **_: object):
        del include_suppressed
        matches = []
        needle = query.lower()
        for node in self.nodes.values():
            if needle in node.id.lower() or needle in node.body.lower():
                matches.append(
                    {
                        "id": node.id,
                        "type": node.node_type,
                        "score": 10,
                        "matched": ["body"],
                        "summary": node.body[:120],
                    }
                )
        return matches[:limit]

    def backlinks(self, node_id: str) -> list[str]:
        return [node.id for node in self.nodes.values() if node_id in node.links]

    def recall_bundle(self, node_id: str, reason: str = "", body_chars: int = 1200):
        node = self.nodes[node_id]
        return {
            "id": node.id,
            "type": node.node_type,
            "summary": node.body[:80],
            "body_excerpt": node.body[:body_chars],
            "links": node.links,
            "backlinks": self.backlinks(node_id),
            "metadata": {},
            "relevance_reason": reason,
            "markdown": (
                f"### {node.id}\n\n"
                f"- Type: `{node.node_type}`\n"
                f"- Backlinks: {', '.join(self.backlinks(node_id)) or 'none'}\n\n"
                f"{node.body[:body_chars]}"
            ),
        }

    def create_memory_node(
        self,
        node_id: str,
        kind: str = "project_fact",
        body: str = "",
        links: list[str] | None = None,
        **context: object,
    ) -> FakeNode:
        node = FakeNode(node_id, kind, body, links or [], f"{node_id}.md")
        self.nodes[node_id] = node
        self.created_memory.append((node_id, kind, body, links or []))
        self.created_contexts.append(context)
        return node

    def update_file(self, path: str) -> str | None:
        self.updated_files.append(path)
        return Path(path).stem

    def changed_since(self, since_unix: int):
        return [
            {"id": node.id, "relative_path": node.relative_path or f"{node.id}.md", "modified_unix": since_unix + 1}
            for node in self.nodes.values()
        ]

    def merge_nodes(self, target_id: str, source_id: str) -> None:
        self.merged.append((target_id, source_id))
        target = self.nodes[target_id]
        source = self.nodes[source_id]
        self.nodes[target_id] = FakeNode(
            target.id,
            target.node_type,
            target.body.rstrip() + "\n\n## Merged Memory\n\n" + source.body,
            target.links,
            target.relative_path,
        )
        del self.nodes[source_id]

    def suppress_node(self, node_id: str, reason: str | None = None) -> None:
        self.suppressed.append((node_id, reason))

    def unsuppress_node(self, node_id: str) -> None:
        self.unsuppressed.append(node_id)


def fake_memory_manager(nodes: dict[str, FakeNode]) -> MemoryManager:
    mgr = MemoryManager.__new__(MemoryManager)
    mgr._index = FakeIndex(nodes)
    mgr.memory_dir = Path("/tmp/magent-test-memory")
    mgr.budget_tokens = 4000
    mgr.max_node_tokens = 220
    mgr.username = None
    mgr.semantic_enabled = False
    mgr.semantic_provider = "ollama"
    mgr.semantic_model = "nomic-embed-text"
    mgr.last_recall_stats = {"nodes": 0, "tokens": 0, "budget": 4000}
    mgr._semantic = None
    return mgr


def test_recall_includes_node_body(tmp_path: Path) -> None:
    (tmp_path / "prefers_pytest.md").write_text(
        '---\nid: "prefers_pytest"\ntype: "preference"\nlinks: []\n---\n'
        "# Prefers Pytest\n\nUser prefers pytest for Python projects.\n",
        encoding="utf-8",
    )

    mgr = MemoryManager(tmp_path)
    recalled = mgr.recall("pytest")

    assert "Prefers Pytest" in recalled
    assert "User prefers pytest" in recalled
    assert "Why These Memories" in recalled


def test_write_bookmark_preserves_url_without_extra_frontmatter(tmp_path: Path) -> None:
    mgr = MemoryManager(tmp_path)

    written = mgr.write_memories(
        [
            {
                "id": "bookmark_docs",
                "type": "bookmark",
                "body": "# Docs",
                "links": ["project_demo"],
                "url": "https://example.com/docs",
                "tags": ["docs", "demo"],
            }
        ],
        project_slug="demo",
    )

    assert written == 1
    node = mgr.read_node("bookmark_docs")
    assert node is not None
    assert "https://example.com/docs" in node["body"]
    assert "Tags: docs, demo" in node["body"]
    assert "[[project_demo]]" in node["body"]


def test_write_memories_uses_maggraph_memory_node_helper() -> None:
    mgr = fake_memory_manager({})

    written = mgr.write_memories(
        [
            {
                "id": "remember_task",
                "type": "fact",
                "body": "# Task\n\nShip it.",
                "links": [],
                "tags": ["task"],
            }
        ]
    )

    assert written == 1
    assert mgr._index.created_memory[0][0] == "remember_task"
    assert mgr._index.created_memory[0][1] == "task"
    assert mgr._index.updated_files


def test_write_memories_passes_scope_and_provenance_to_modern_maggraph() -> None:
    mgr = fake_memory_manager({})
    mgr.project_slug = "demo"

    written = mgr.write_memories(
        [
            {
                "id": "decision_runtime",
                "type": "pattern",
                "body": "Use durable tasks.",
                "source_task": "task_42",
                "source_session": "session_7",
                "confidence": 0.9,
                "canonical_id": "runtime-decision",
            }
        ]
    )

    assert written == 1
    assert mgr._index.created_contexts[0] == {
        "project": "demo",
        "source_task": "task_42",
        "source_session": "session_7",
        "extraction_method": "agent_extraction",
        "confidence": 0.9,
        "canonical_id": "runtime-decision",
    }


def test_hybrid_search_routes_sidecar_scores_into_maggraph() -> None:
    class HybridIndex(FakeIndex):
        def __init__(self):
            super().__init__({"pref": FakeNode("pref", "preference", "Use pytest.", [])})
            self.hybrid_kwargs = {}

        def hybrid_search(self, **kwargs):
            self.hybrid_kwargs = kwargs
            return [
                {
                    "id": "pref",
                    "type": "preference",
                    "score": 0.87,
                    "signals": {"semantic": 0.8, "lexical": 0.6},
                    "reasons": ["semantic match", "lexical match"],
                    "summary": "Use pytest.",
                }
            ]

    class SemanticItem:
        node_id = "pref"
        semantic_score = 0.8

    class SemanticIndex:
        def search(self, query: str, top_k: int, mode: str):
            assert (query, mode) == ("pytest", "semantic")
            assert top_k >= 10
            return [SemanticItem()]

    mgr = fake_memory_manager({})
    mgr._index = HybridIndex()
    mgr.username = "alice"
    mgr.semantic_enabled = True
    mgr.project_slug = "demo"
    mgr._semantic = SemanticIndex()

    results = mgr.search("pytest", mode="hybrid")

    assert results[0]["reason"] == "semantic match, lexical match"
    assert mgr._index.hybrid_kwargs["project"] == "demo"
    assert mgr._index.hybrid_kwargs["semantic_scores"] == {"pref": 0.8}
    assert mgr._index.hybrid_kwargs["seed_ids"] == ["pref"]


def test_reviewed_batch_delegates_to_maggraph() -> None:
    mgr = fake_memory_manager({})
    operations = [{"op": "suppress", "id": "stale", "reason": "old"}]
    calls = []

    def apply_memory_batch(items, preview=False):
        calls.append((items, preview))
        return {"ok": True, "preview": preview, "operations": len(items)}

    mgr._index.apply_memory_batch = apply_memory_batch

    result = mgr.apply_batch(operations, preview=True)

    assert result == {"ok": True, "preview": True, "operations": 1}
    assert calls == [(operations, True)]


def test_candidate_assessment_detects_duplicate_and_identity_conflict() -> None:
    mgr = fake_memory_manager(
        {
            "same_body": FakeNode("same_body", "project_fact", "Use durable tasks.", []),
            "decision": FakeNode("decision", "decision", "Use the old queue.", []),
        }
    )

    duplicate = mgr.assess_candidate({"id": "new", "body": "  use durable   tasks. "})
    conflict = mgr.assess_candidate({"id": "decision", "body": "Use task runtime."})

    assert duplicate["duplicates"] == ["same_body"]
    assert duplicate["requires_review"] is True
    assert conflict["conflicts"] == ["decision"]


def test_search_uses_maggraph_native_search_and_backlinks() -> None:
    mgr = fake_memory_manager(
        {
            "pref": FakeNode("pref", "preference", "Use pytest.", []),
            "project": FakeNode("project", "project_fact", "Links to pref.", ["pref"]),
        }
    )

    results = mgr.search("pytest")

    assert results[0]["id"] == "pref"
    assert results[0]["matched"] == ["body"]
    assert results[0]["backlinks"] == ["project"]


def test_empty_native_search_does_not_leak_filtered_nodes_from_raw_scan() -> None:
    mgr = fake_memory_manager(
        {"stale": FakeNode("stale", "project_fact", "Hidden durable fact.", [])}
    )
    mgr._index.search = lambda **kwargs: []

    assert mgr.search("durable") == []
    assert mgr.recall("durable") == ""


def test_recall_uses_bundle_backlinks_for_provenance() -> None:
    mgr = fake_memory_manager(
        {
            "pref": FakeNode("pref", "preference", "User prefers pytest.", []),
            "project": FakeNode("project", "project_fact", "Project links.", ["pref"]),
        }
    )

    recalled = mgr.recall("pytest")

    assert "Why These Memories" in recalled
    assert "backlinks: `project`" in recalled
    assert "Backlinks: project" in recalled


def test_quality_report_finds_duplicate_and_suppressed_nodes() -> None:
    mgr = fake_memory_manager(
        {
            "pref_one": FakeNode("pref_one", "preference", "Use pytest for tests.", []),
            "pref_two": FakeNode("pref_two", "preference", "Use pytest for tests.", []),
            "old_pref": FakeNode("old_pref", "preference", "Stale\n\nSuppressed: true", []),
        }
    )

    report = mgr.quality_report()

    assert report["ok"] is True
    assert report["nodes"] == 3
    assert report["duplicates"] == [["pref_one", "pref_two"]]
    assert report["suppressed"] == ["old_pref"]
    assert report["duplicate_groups"] == 1


def test_merge_nodes_updates_target_and_deletes_source() -> None:
    mgr = fake_memory_manager(
        {
            "target": FakeNode("target", "fact", "Target body", []),
            "source": FakeNode("source", "fact", "Source body", []),
        }
    )

    result = mgr.merge_nodes("target", "source")

    assert result == {"ok": True, "target": "target", "deleted": "source"}
    assert "Source body" in mgr._index.nodes["target"].body
    assert "source" not in mgr._index.nodes
    assert mgr._index.merged == [("target", "source")]


def test_merge_preview_does_not_modify_nodes() -> None:
    mgr = fake_memory_manager(
        {
            "target": FakeNode("target", "fact", "Target body", []),
            "source": FakeNode("source", "fact", "Source body", []),
        }
    )

    result = mgr.merge_preview("target", "source")

    assert result["ok"] is True
    assert result["target"] == "target"
    assert result["source"] == "source"
    assert "Source body" in result["preview"]
    assert mgr._index.updated == []
    assert "source" in mgr._index.nodes


def test_suppress_node_marks_node_without_deleting() -> None:
    mgr = fake_memory_manager({"old_pref": FakeNode("old_pref", "preference", "Old body", [])})

    result = mgr.suppress_node("old_pref", reason="stale")

    assert result == {"ok": True, "id": "old_pref", "reason": "stale"}
    assert mgr._index.suppressed == [("old_pref", "stale")]


def test_unsuppress_node_removes_suppression_markers() -> None:
    mgr = fake_memory_manager(
        {
            "old_pref": FakeNode(
                "old_pref",
                "preference",
                "Old body\n\nSuppressed: true\nSuppressReason: stale\n",
                [],
            )
        }
    )

    result = mgr.unsuppress_node("old_pref")

    assert result == {"ok": True, "id": "old_pref"}
    assert mgr._index.unsuppressed == ["old_pref"]


def test_changed_since_delegates_to_maggraph_change_feed() -> None:
    mgr = fake_memory_manager({"pref": FakeNode("pref", "preference", "Body", [], "pref.md")})

    changes = mgr.changed_since(100)

    assert changes == [{"id": "pref", "relative_path": "pref.md", "modified_unix": 101}]


def test_update_node_replaces_body_and_preserves_links() -> None:
    mgr = fake_memory_manager({"pref": FakeNode("pref", "preference", "Old body", [], "pref.md")})

    result = mgr.update_node("pref", body="# New body", links=["project_demo"])

    assert result["ok"] is True
    assert "[[project_demo]]" in mgr._index.nodes["pref"].body
    assert mgr._index.updated_files
