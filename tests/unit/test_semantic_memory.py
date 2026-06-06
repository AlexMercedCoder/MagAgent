from __future__ import annotations

from types import SimpleNamespace

from magent.semantic_memory import SemanticMemoryIndex, chunk_text, local_hash_embedding


class FakeIndex:
    def __init__(self):
        self.nodes = {
            "jwt_refresh_bug": SimpleNamespace(
                id="jwt_refresh_bug",
                node_type="error_pattern",
                body="Refresh tokens expired early because clock skew was not tolerated.",
                links=[],
            ),
            "ui_preference": SimpleNamespace(
                id="ui_preference",
                node_type="preference",
                body="The user likes compact dashboards with clear tables.",
                links=[],
            ),
        }

    def list_nodes(self):
        return list(self.nodes)

    def read_node(self, node_id):
        return self.nodes[node_id]


def test_local_hash_embedding_is_stable():
    assert local_hash_embedding("refresh token bug") == local_hash_embedding("refresh token bug")


def test_chunk_text_returns_chunks():
    chunks = chunk_text("one two three\n\nfour five six", max_words=3, overlap_words=1)
    assert chunks
    assert "one" in chunks[0]


def test_semantic_index_reindex_and_search(tmp_path, monkeypatch):
    monkeypatch.setattr("magent.semantic_memory.USERS_DIR", tmp_path)
    index = SemanticMemoryIndex(
        "alice",
        tmp_path / "memory",
        provider="local-hash",
        model="local-hash",
    )

    result = index.reindex(FakeIndex())
    assert result["ok"] is True
    assert result["chunks_indexed"] >= 2

    matches = index.search("refresh token expires", mode="hybrid")
    assert matches
    assert matches[0].node_id == "jwt_refresh_bug"
