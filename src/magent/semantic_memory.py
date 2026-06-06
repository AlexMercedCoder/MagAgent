"""Local semantic sidecar index for MagGraph memory nodes."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
import sqlite3
import urllib.request
from array import array
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from magent.config import USERS_DIR

DEFAULT_DIM = 256
DEFAULT_MODEL = "nomic-embed-text"


@dataclass(frozen=True)
class SemanticSearchResult:
    node_id: str
    chunk_id: int
    node_type: str
    text: str
    score: float
    semantic_score: float
    keyword_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "chunk_id": self.chunk_id,
            "type": self.node_type,
            "snippet": self.text[:240].replace("\n", " "),
            "score": round(self.score, 4),
            "semantic_score": round(self.semantic_score, 4),
            "keyword_score": round(self.keyword_score, 4),
        }


class SemanticMemoryIndex:
    """SQLite vector cache for local memory graph chunks.

    MagGraph remains the source of truth. This index stores derived embeddings
    only, and can be reset/rebuilt at any time.
    """

    def __init__(
        self,
        username: str,
        memory_dir: Path,
        provider: str = "ollama",
        model: str = DEFAULT_MODEL,
        dim: int = DEFAULT_DIM,
    ):
        self.username = username
        self.memory_dir = memory_dir
        self.provider = provider
        self.model = model
        self.dim = dim
        self.root = USERS_DIR / username / "workbench" / "vector"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "memory_index.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    node_id TEXT NOT NULL,
                    chunk_id INTEGER NOT NULL,
                    node_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    embedding_model TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (node_id, chunk_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_hash "
                "ON memory_embeddings(node_id, content_hash)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def reset(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        self._init_db()

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*), COUNT(DISTINCT node_id) FROM memory_embeddings").fetchone()
            models = conn.execute(
                "SELECT embedding_model, COUNT(*) FROM memory_embeddings GROUP BY embedding_model"
            ).fetchall()
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "chunks": int(row[0] or 0),
            "nodes": int(row[1] or 0),
            "models": [{"model": model, "chunks": count} for model, count in models],
            "provider": self.provider,
            "model": self.model,
        }

    def reindex(self, maggraph_index: Any) -> dict[str, Any]:
        if maggraph_index is None:
            return {"ok": False, "error": "Memory graph unavailable"}

        ids = list(maggraph_index.list_nodes())
        seen_keys: set[tuple[str, int]] = set()
        indexed = 0
        skipped = 0

        with self._connect() as conn:
            for node_id in ids:
                try:
                    node = maggraph_index.read_node(node_id)
                except Exception:
                    continue
                text = _node_text(node)
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                current = conn.execute(
                    "SELECT COUNT(*) FROM memory_embeddings WHERE node_id = ? AND content_hash = ?",
                    (node_id, content_hash),
                ).fetchone()[0]
                chunks = chunk_text(text)
                if current == len(chunks):
                    skipped += 1
                    for chunk_id in range(len(chunks)):
                        seen_keys.add((node_id, chunk_id))
                    continue

                conn.execute("DELETE FROM memory_embeddings WHERE node_id = ?", (node_id,))
                for chunk_id, chunk in enumerate(chunks):
                    vec = self.embed(chunk)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO memory_embeddings
                        (node_id, chunk_id, node_type, text, embedding, embedding_dim,
                         embedding_model, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            node_id,
                            chunk_id,
                            getattr(node, "node_type", "") or "unknown",
                            chunk,
                            _pack_vector(vec),
                            len(vec),
                            self.model,
                            content_hash,
                        ),
                    )
                    seen_keys.add((node_id, chunk_id))
                    indexed += 1

            all_rows = conn.execute("SELECT node_id, chunk_id FROM memory_embeddings").fetchall()
            for node_id, chunk_id in all_rows:
                if node_id not in ids or (node_id, chunk_id) not in seen_keys:
                    conn.execute(
                        "DELETE FROM memory_embeddings WHERE node_id = ? AND chunk_id = ?",
                        (node_id, chunk_id),
                    )

        return {"ok": True, "nodes_seen": len(ids), "chunks_indexed": indexed, "nodes_skipped": skipped}

    def search(self, query: str, top_k: int = 8, mode: str = "hybrid") -> list[SemanticSearchResult]:
        query = query.strip()
        if not query:
            return []
        mode = mode.lower()
        query_vec = self.embed(query) if mode in {"semantic", "hybrid"} else []
        query_terms = _terms(query)

        rows: list[tuple[str, int, str, str, bytes, int]] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT node_id, chunk_id, node_type, text, embedding, embedding_dim FROM memory_embeddings"
            ).fetchall()

        scored_rows = []
        for node_id, chunk_id, node_type, text, blob, dim in rows:
            lexical_score = keyword_score(query_terms, text)
            if mode == "hybrid" and lexical_score <= 0 and len(rows) > 1000:
                continue
            semantic_score = 0.0
            if query_vec:
                vec = _unpack_vector(blob, dim)
                semantic_score = cosine(query_vec, vec)
            if mode == "semantic":
                score = semantic_score
            elif mode == "keyword":
                score = lexical_score
            else:
                score = (semantic_score * 0.72) + (lexical_score * 0.28)
            if score > 0:
                scored_rows.append(
                    (
                        score,
                        SemanticSearchResult(
                            node_id=node_id,
                            chunk_id=int(chunk_id),
                            node_type=node_type,
                            text=text,
                            score=score,
                            semantic_score=semantic_score,
                            keyword_score=lexical_score,
                        ),
                    )
                )

        top_candidates = heapq.nlargest(max(top_k * 4, top_k), scored_rows, key=lambda item: item[0])
        deduped: list[SemanticSearchResult] = []
        seen_nodes: set[str] = set()
        for _, item in top_candidates:
            if item.node_id in seen_nodes:
                continue
            seen_nodes.add(item.node_id)
            deduped.append(item)
            if len(deduped) >= top_k:
                break
        return deduped

    def embed(self, text: str) -> list[float]:
        if self.provider == "ollama":
            try:
                return _ollama_embedding(text, self.model)
            except Exception:
                pass
        return local_hash_embedding(text, dim=self.dim)


def chunk_text(text: str, max_words: int = 180, overlap_words: int = 30) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    for paragraph in paragraphs:
        words = paragraph.split()
        if len(current) + len(words) > max_words and current:
            chunks.append(" ".join(current))
            current = current[-overlap_words:] if overlap_words else []
        current.extend(words)
        while len(current) >= max_words:
            chunks.append(" ".join(current[:max_words]))
            current = current[max(1, max_words - overlap_words) :]
    if current:
        chunks.append(" ".join(current))
    return chunks or [text.strip()]


def local_hash_embedding(text: str, dim: int = DEFAULT_DIM) -> list[float]:
    vec = [0.0] * dim
    for term, count in Counter(_terms(text)).items():
        digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = -1.0 if digest[4] & 1 else 1.0
        vec[idx] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    denom = math.sqrt(sum(x * x for x in a[:n])) * math.sqrt(sum(y * y for y in b[:n]))
    if not denom:
        return 0.0
    return max(0.0, sum(a[i] * b[i] for i in range(n)) / denom)


def keyword_score(query_terms: list[str], text: str) -> float:
    if not query_terms:
        return 0.0
    haystack = set(_terms(text))
    return len(set(query_terms) & haystack) / max(len(set(query_terms)), 1)


def _terms(text: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9_]{2,}", text.lower()) if term not in _STOPWORDS]


def _node_text(node: Any) -> str:
    links = ", ".join(getattr(node, "links", []) or [])
    return "\n".join(
        [
            f"# {getattr(node, 'id', '')}",
            f"Type: {getattr(node, 'node_type', '')}",
            f"Links: {links}",
            "",
            getattr(node, "body", "") or "",
        ]
    ).strip()


def _ollama_embedding(text: str, model: str) -> list[float]:
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:11434/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
    embedding = data.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("Ollama returned no embedding")
    return [float(value) for value in embedding]


def _pack_vector(values: list[float]) -> bytes:
    return array("f", values).tobytes()


def _unpack_vector(blob: bytes, dim: int) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values[:dim])


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "you",
    "your",
    "are",
    "was",
    "were",
    "has",
    "have",
    "not",
    "but",
    "use",
    "using",
}
