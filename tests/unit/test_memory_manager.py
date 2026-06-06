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


def fake_memory_manager(nodes: dict[str, FakeNode]) -> MemoryManager:
    mgr = MemoryManager.__new__(MemoryManager)
    mgr._index = FakeIndex(nodes)
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
    assert "Merged-from: [[source]]" in mgr._index.nodes["target"].body
    assert "source" not in mgr._index.nodes
    assert mgr._index.deleted == ["source"]


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
    assert "Suppressed: true" in mgr._index.nodes["old_pref"].body
    assert "SuppressReason: stale" in mgr._index.nodes["old_pref"].body


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
    assert "Suppressed: true" not in mgr._index.nodes["old_pref"].body
    assert "SuppressReason" not in mgr._index.nodes["old_pref"].body
