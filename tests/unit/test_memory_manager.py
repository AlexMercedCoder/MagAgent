"""Tests for MagGraph-backed memory behavior."""

from pathlib import Path

from magent.memory import MemoryManager


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
