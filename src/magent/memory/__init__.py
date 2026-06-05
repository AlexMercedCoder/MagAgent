"""MagGraph memory integration for MagAgent.

Manages per-user knowledge graph operations:
- Pre-task recall (BFS traversal)
- Post-task memory extraction + writes
- Bookmark nodes
- Stats, search, show, traverse, delete, export, log, reset
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

# Node type constants
NODE_PREFERENCE = "preference"
NODE_PROJECT = "project"
NODE_PATTERN = "pattern"
NODE_SKILL_LEARNED = "skill_learned"
NODE_FACT = "fact"
NODE_SESSION_SUMMARY = "session_summary"
NODE_ERROR_PATTERN = "error_pattern"
NODE_CONTACT = "contact"
NODE_BOOKMARK = "bookmark"

ALL_NODE_TYPES = [
    NODE_PREFERENCE, NODE_PROJECT, NODE_PATTERN, NODE_SKILL_LEARNED,
    NODE_FACT, NODE_SESSION_SUMMARY, NODE_ERROR_PATTERN, NODE_CONTACT,
    NODE_BOOKMARK,
]


class MemoryManager:
    """Manages a user's MagGraph knowledge graph."""

    def __init__(self, memory_dir: Path, budget_tokens: int = 4000):
        self.memory_dir = memory_dir
        self.budget_tokens = budget_tokens
        self._index = None
        self._init_graph()

    def _init_graph(self) -> None:
        """Open or initialize the MagGraph index."""
        try:
            import maggraph
            self._index = maggraph.open_index(str(self.memory_dir))
        except ImportError:
            console.print(
                "[yellow]⚠ maggraph not installed — memory features disabled.[/yellow]\n"
                "  Install with: [bold]pip install maggraph[/bold]"
            )
            self._index = None
        except Exception as e:
            console.print(f"[yellow]⚠ Could not open memory graph: {e}[/yellow]")
            self._index = None

    @property
    def available(self) -> bool:
        return self._index is not None

    # ─────────────────────────────────────────────
    # Pre-task recall
    # ─────────────────────────────────────────────

    def recall(self, query: str, depth: int = 2) -> str:
        """
        Find relevant memory nodes for a query and return Markdown context.
        Returns empty string if memory unavailable or no relevant nodes found.
        """
        if not self.available:
            return ""

        anchor_ids = self._find_anchor_nodes(query, max_anchors=3)
        if not anchor_ids:
            return ""

        sections: list[str] = []
        seen_ids: set[str] = set()

        for anchor_id in anchor_ids:
            try:
                result = self._index.traverse(anchor_id, depth=depth, order="bfs")
                for node in result.nodes:
                    if node.id not in seen_ids:
                        seen_ids.add(node.id)
                report = result.to_markdown(self._index)
                sections.append(report)
            except Exception:
                pass

        combined = "\n\n---\n\n".join(sections)

        # Rough token budget enforcement (4 chars ≈ 1 token)
        max_chars = self.budget_tokens * 4
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n\n[...memory truncated for context budget...]"

        return combined

    def _find_anchor_nodes(self, query: str, max_anchors: int = 3) -> list[str]:
        """Find node IDs most relevant to query via keyword matching."""
        if not self.available:
            return []

        try:
            all_ids = self._index.list_nodes()
        except Exception:
            return []

        query_words = set(re.sub(r"[^\w\s]", " ", query.lower()).split())
        if not query_words:
            return []

        scored: list[tuple[float, str]] = []
        for node_id in all_ids:
            id_words = set(re.sub(r"[^\w]", " ", node_id).split())
            score = len(query_words & id_words) / max(len(query_words), 1)
            if score > 0:
                scored.append((score, node_id))

        # Also scan node bodies for top matches (sample first 50 nodes)
        sample_ids = all_ids[:50]
        for node_id in sample_ids:
            if any(nid == node_id for _, nid in scored):
                continue
            try:
                node = self._index.read_node(node_id)
                body_words = set(re.sub(r"[^\w\s]", " ", node.body.lower()).split())
                score = len(query_words & body_words) / max(len(query_words), 1)
                if score > 0.1:
                    scored.append((score * 0.5, node_id))  # body matches weighted lower
            except Exception:
                pass

        scored.sort(reverse=True)
        return [nid for _, nid in scored[:max_anchors]]

    # ─────────────────────────────────────────────
    # Post-task memory write
    # ─────────────────────────────────────────────

    def write_memories(
        self,
        extracted: list[dict[str, Any]],
        project_slug: str | None = None,
    ) -> int:
        """
        Write extracted memory nodes to the graph.
        Returns count of nodes written.

        Each item in extracted should have:
          {
            "id": "node_id",
            "type": "preference|project|...",
            "body": "# Markdown body...",
            "links": ["other_node_id"],
            "url": "https://...",   # for bookmarks
            "tags": ["tag1"],        # for bookmarks
          }
        """
        if not self.available:
            return 0

        written = 0
        for item in extracted:
            node_id = item.get("id", "").strip().replace(" ", "_")
            if not node_id:
                continue

            node_type = item.get("type", NODE_FACT)
            body = item.get("body", "")
            links = item.get("links", [])

            # Inject project link if applicable
            if project_slug and project_slug not in links:
                project_node_id = f"project_{project_slug}"
                body = body.rstrip() + f"\n\nProject: [[{project_node_id}]]\n"
                links = list(links) + [project_node_id]

            # Extra frontmatter for bookmark nodes
            extra: dict[str, Any] = {}
            if node_type == NODE_BOOKMARK:
                if url := item.get("url"):
                    extra["url"] = url
                if tags := item.get("tags"):
                    extra["tags"] = tags

            try:
                existing_ids = self._index.list_nodes()
                if node_id in existing_ids:
                    self._index.update_node(node_id, body)
                else:
                    self._index.create_node(
                        node_id,
                        node_type=node_type,
                        body=body,
                        links=links,
                        **extra,
                    )
                written += 1
            except Exception as e:
                console.print(f"[dim red]Memory write failed for '{node_id}': {e}[/dim red]")

        return written

    def write_session_summary(self, session_id: str, summary: str) -> None:
        """Write a session summary node."""
        if not self.available:
            return
        node_id = f"session_{session_id}"
        try:
            self._index.create_node(
                node_id,
                node_type=NODE_SESSION_SUMMARY,
                body=f"# Session {session_id}\n\n{summary}\n",
                links=[],
            )
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # Stats
    # ─────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Collect graph statistics."""
        result: dict[str, Any] = {
            "nodes": 0,
            "edges_total": 0,
            "node_types": {},
            "disk_bytes": 0,
            "git_commits": 0,
            "git_history_bytes": 0,
            "last_modified": None,
            "avg_node_bytes": 0,
            "largest_node_bytes": 0,
        }

        if not self.available:
            return result

        try:
            all_ids = self._index.list_nodes()
            result["nodes"] = len(all_ids)

            total_bytes = 0
            largest = 0
            edge_count = 0

            for node_id in all_ids:
                try:
                    node = self._index.read_node(node_id)
                    body_bytes = len(node.body.encode())
                    total_bytes += body_bytes
                    if body_bytes > largest:
                        largest = body_bytes
                    edge_count += len(node.links or [])
                    ntype = node.node_type or "unknown"
                    result["node_types"][ntype] = result["node_types"].get(ntype, 0) + 1
                except Exception:
                    pass

            result["edges_total"] = edge_count
            result["avg_node_bytes"] = total_bytes // max(len(all_ids), 1)
            result["largest_node_bytes"] = largest

        except Exception as e:
            console.print(f"[dim red]Stats collection error: {e}[/dim red]")

        # Disk usage
        try:
            total_disk = sum(
                f.stat().st_size
                for f in self.memory_dir.rglob("*")
                if f.is_file()
            )
            result["disk_bytes"] = total_disk
        except Exception:
            pass

        # Git info
        try:
            import subprocess
            git_log = subprocess.run(
                ["git", "log", "--oneline"],
                cwd=self.memory_dir,
                capture_output=True,
                text=True,
            )
            if git_log.returncode == 0:
                result["git_commits"] = len(git_log.stdout.strip().splitlines())

            git_size = subprocess.run(
                ["git", "count-objects", "-vH"],
                cwd=self.memory_dir,
                capture_output=True,
                text=True,
            )
            if git_size.returncode == 0:
                for line in git_size.stdout.splitlines():
                    if line.startswith("size:"):
                        val = line.split(":")[1].strip()
                        result["git_history_bytes_human"] = val
        except Exception:
            pass

        # Last modified
        try:
            md_files = list(self.memory_dir.rglob("*.md"))
            if md_files:
                latest = max(f.stat().st_mtime for f in md_files)
                result["last_modified"] = datetime.fromtimestamp(latest).isoformat()
        except Exception:
            pass

        return result

    # ─────────────────────────────────────────────
    # Search
    # ─────────────────────────────────────────────

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Full-text search over node bodies and IDs."""
        if not self.available:
            return []

        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        try:
            for node_id in self._index.list_nodes():
                try:
                    node = self._index.read_node(node_id)
                    if query_lower in node_id.lower() or query_lower in node.body.lower():
                        results.append({
                            "id": node.id,
                            "type": node.node_type,
                            "snippet": node.body[:200].replace("\n", " "),
                        })
                        if len(results) >= max_results:
                            break
                except Exception:
                    pass
        except Exception:
            pass

        return results

    def read_node(self, node_id: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            node = self._index.read_node(node_id)
            return {
                "id": node.id,
                "type": node.node_type,
                "body": node.body,
                "links": node.links,
                "path": node.relative_path,
            }
        except Exception:
            return None

    def traverse_node(self, node_id: str, depth: int = 2) -> str:
        if not self.available:
            return ""
        try:
            result = self._index.traverse(node_id, depth=depth, order="bfs")
            return result.to_markdown(self._index)
        except Exception as e:
            return f"Error traversing '{node_id}': {e}"

    def delete_node(self, node_id: str) -> bool:
        if not self.available:
            return False
        try:
            self._index.delete_node(node_id)
            return True
        except Exception:
            return False

    def list_nodes(self) -> list[str]:
        if not self.available:
            return []
        try:
            return self._index.list_nodes()
        except Exception:
            return []

    def export_json(self) -> list[dict[str, Any]]:
        """Export all nodes as a list of dicts."""
        if not self.available:
            return []
        nodes = []
        for node_id in self.list_nodes():
            n = self.read_node(node_id)
            if n:
                nodes.append(n)
        return nodes
