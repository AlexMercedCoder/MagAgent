"""MagGraph memory integration for MagAgent.

Manages per-user knowledge graph operations:
- Pre-task recall (BFS traversal)
- Post-task memory extraction + writes
- Bookmark nodes
- Stats, search, show, traverse, delete, export, log, reset
"""

from __future__ import annotations

import contextlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from magent.tokens import estimate_tokens, truncate_to_tokens

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
    NODE_PREFERENCE,
    NODE_PROJECT,
    NODE_PATTERN,
    NODE_SKILL_LEARNED,
    NODE_FACT,
    NODE_SESSION_SUMMARY,
    NODE_ERROR_PATTERN,
    NODE_CONTACT,
    NODE_BOOKMARK,
]

MAGGRAPH_MEMORY_KIND_BY_TYPE = {
    NODE_PREFERENCE: "preference",
    NODE_PROJECT: "project_fact",
    NODE_PATTERN: "decision",
    NODE_SKILL_LEARNED: "decision",
    NODE_FACT: "project_fact",
    NODE_SESSION_SUMMARY: "session_summary",
    NODE_ERROR_PATTERN: "tool_failure",
    NODE_CONTACT: "project_fact",
    NODE_BOOKMARK: "bookmark",
}


class MemoryManager:
    """Manages a user's MagGraph knowledge graph."""

    def __init__(
        self,
        memory_dir: Path,
        budget_tokens: int = 4000,
        max_node_tokens: int = 220,
        username: str | None = None,
        semantic_enabled: bool = False,
        semantic_provider: str = "ollama",
        semantic_model: str = "nomic-embed-text",
    ):
        self.memory_dir = memory_dir
        self.budget_tokens = budget_tokens
        self.max_node_tokens = max_node_tokens
        self.username = username
        self.semantic_enabled = semantic_enabled
        self.semantic_provider = semantic_provider
        self.semantic_model = semantic_model
        self.last_recall_stats: dict[str, int] = {"nodes": 0, "tokens": 0, "budget": budget_tokens}
        self._index = None
        self._semantic = None
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

        anchors = self._find_anchor_nodes(query, max_anchors=3)
        anchor_ids = [item["id"] for item in anchors]
        if not anchor_ids:
            return ""

        rendered = self._format_recall_nodes(anchors, depth=depth)
        self.last_recall_stats = {
            "nodes": len(anchor_ids),
            "tokens": estimate_tokens(rendered),
            "budget": self.budget_tokens,
        }
        return rendered

    def _format_recall_nodes(self, anchors: list[dict[str, Any]], depth: int = 2) -> str:
        """Render compact graph-native recall bundles with provenance."""
        if not anchors:
            return ""

        budget = self.budget_tokens
        excerpt_budget = max(40, self.max_node_tokens)
        anchor_ids = [item["id"] for item in anchors]
        lines = [
            "# MagAgent Memory Recall",
            "",
            f"- Anchors: {', '.join(f'`{node_id}`' for node_id in anchor_ids)}",
            f"- Nodes considered: {len(anchor_ids)}",
            f"- Budget: ~{budget} tokens",
            "",
            "## Why These Memories",
            "",
        ]

        for anchor in anchors:
            matched = ", ".join(anchor.get("matched", [])) or "graph search"
            backlinks = ", ".join(f"`{item}`" for item in anchor.get("backlinks", [])) or "none"
            lines.append(
                f"- `{anchor['id']}` matched {matched}; score {anchor.get('score', '')}; backlinks: {backlinks}"
            )

        lines.extend(
            [
                "",
                "## Recall Bundles",
                "",
            ]
        )

        bundles = self._recall_bundles(anchors, body_chars=excerpt_budget * 4)
        if bundles:
            for bundle in bundles:
                markdown = str(bundle.get("markdown") or "").strip()
                if markdown:
                    lines.extend([markdown, ""])
                    continue
                backlinks = ", ".join(f"`{item}`" for item in bundle.get("backlinks", [])) or "none"
                links = ", ".join(f"`{item}`" for item in bundle.get("links", [])) or "none"
                lines.extend(
                    [
                        f"### {bundle.get('id', '')}",
                        "",
                        f"- Type: `{bundle.get('type', '')}`",
                        f"- Links: {links}",
                        f"- Backlinks: {backlinks}",
                        f"- Reason: {bundle.get('relevance_reason', '')}",
                        "",
                        truncate_to_tokens(str(bundle.get("body_excerpt", "")), excerpt_budget),
                        "",
                    ]
                )
            return truncate_to_tokens(
                "\n".join(lines).strip(),
                budget,
                "[...memory truncated for context budget...]",
            )

        node_ids = self._expanded_node_ids(anchor_ids, depth=depth)
        lines.extend(
            [
            "## Compact Matches",
            "",
            ]
        )

        loaded: list[Any] = []
        for node_id in node_ids:
            try:
                loaded.append(self._index.read_node(node_id))
            except Exception:
                continue

        for node in loaded:
            snippet = _first_sentence_or_line(node.body)
            links = ", ".join(node.links or []) or "none"
            lines.append(
                f"- `{node.id}` ({node.node_type}; links: {links}): "
                f"{truncate_to_tokens(snippet, 45, '[...]')}"
            )

        lines.extend(["", "## Excerpts", ""])
        excerpt_count = 0
        for node in loaded:
            if excerpt_count >= 4:
                break
            body = truncate_to_tokens((node.body or "").strip(), excerpt_budget)
            if not body:
                continue
            lines.extend(
                [
                    f"### {node.id}",
                    "",
                    f"- Type: `{node.node_type}`",
                    "",
                    body,
                    "",
                ]
            )
            excerpt_count += 1

            current = "\n".join(lines)
            if estimate_tokens(current) >= budget:
                break

        rendered = "\n".join(lines).strip()
        return truncate_to_tokens(rendered, budget, "[...memory truncated for context budget...]")

    def _recall_bundles(self, anchors: list[dict[str, Any]], body_chars: int) -> list[dict[str, Any]]:
        """Return MagGraph recall bundles when available."""
        if not hasattr(self._index, "recall_bundle"):
            return []
        bundles: list[dict[str, Any]] = []
        for anchor in anchors:
            try:
                bundle = self._index.recall_bundle(
                    anchor["id"],
                    reason=anchor.get("reason", ""),
                    body_chars=body_chars,
                )
                bundles.append(dict(bundle))
            except Exception:
                continue
        return bundles

    def _expanded_node_ids(self, anchor_ids: list[str], depth: int = 2) -> list[str]:
        """Fallback traversal expansion for MagGraph versions without recall bundles."""
        ordered_ids: list[str] = []
        seen_ids: set[str] = set()
        for anchor_id in anchor_ids:
            try:
                result = self._index.traverse(anchor_id, depth=depth, order="bfs")
                for node in result.nodes:
                    if node.id not in seen_ids:
                        seen_ids.add(node.id)
                        ordered_ids.append(node.id)
            except Exception:
                if anchor_id not in seen_ids:
                    seen_ids.add(anchor_id)
                    ordered_ids.append(anchor_id)
        return ordered_ids

    def _find_anchor_nodes(self, query: str, max_anchors: int = 3) -> list[dict[str, Any]]:
        """Find node IDs most relevant to query via semantic and graph-native keyword matching."""
        if not self.available:
            return []

        semantic_results: list[dict[str, Any]] = []
        if self.semantic_enabled and self.username:
            try:
                semantic_results = self.semantic_search(query, max_results=max_anchors, mode="hybrid")
            except Exception:
                semantic_results = []

        native_results = self._native_search(query, max_results=max_anchors)
        if native_results:
            return _merge_anchor_results(semantic_results, native_results, max_anchors)

        try:
            all_ids = self._index.list_nodes()
        except Exception:
            return _merge_anchor_results(semantic_results, [], max_anchors)

        query_words = set(re.sub(r"[^\w\s]", " ", query.lower()).split())
        if not query_words:
            return []

        scored: list[tuple[float, str]] = []
        for node_id in all_ids:
            id_words = set(re.sub(r"[^\w]", " ", node_id).split())
            score = len(query_words & id_words) / max(len(query_words), 1)
            if score > 0:
                scored.append((score, node_id))

        # Also scan node bodies. Memory graphs are local Markdown and usually small
        # enough that a full lightweight scan is more useful than sampling.
        for node_id in all_ids:
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
        keyword_results = [
            {"id": nid, "type": "", "score": score, "matched": ["fallback_keyword"], "reason": "fallback keyword scan"}
            for score, nid in scored[:max_anchors]
        ]
        return _merge_anchor_results(semantic_results, keyword_results, max_anchors)

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

            if links:
                missing_wikilinks = [
                    link for link in links if f"[[{link}]]" not in body and f"[[{link}|" not in body
                ]
                if missing_wikilinks:
                    body = body.rstrip() + "\n\nRelated: " + ", ".join(
                        f"[[{link}]]" for link in missing_wikilinks
                    ) + "\n"

            # Inject project link if applicable
            if project_slug and project_slug not in links:
                project_node_id = f"project_{project_slug}"
                body = body.rstrip() + f"\n\nProject: [[{project_node_id}]]\n"
                links = list(links) + [project_node_id]

            # The current MagGraph Python binding does not expose arbitrary extra
            # frontmatter fields, so preserve bookmark metadata in Markdown.
            if node_type == NODE_BOOKMARK:
                if url := item.get("url"):
                    body = body.rstrip() + f"\n\nURL: {url}\n"
                if tags := item.get("tags"):
                    body = body.rstrip() + f"\nTags: {', '.join(map(str, tags))}\n"

            try:
                existing = self.read_node(node_id)
                if existing:
                    self._index.update_node(node_id, body)
                    self._refresh_changed_file(node_id)
                elif hasattr(self._index, "create_memory_node"):
                    kind = self._memory_kind_for_item(item)
                    self._index.create_memory_node(
                        node_id,
                        kind=kind,
                        body=body,
                        links=links,
                    )
                    self._refresh_changed_file(node_id)
                else:
                    self._index.create_node(
                        node_id,
                        node_type=node_type,
                        body=body,
                        links=links,
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
        with contextlib.suppress(Exception):
            body = f"# Session {session_id}\n\n{summary}\n"
            if hasattr(self._index, "create_memory_node"):
                self._index.create_memory_node(node_id, kind="session_summary", body=body, links=[])
            else:
                self._index.create_node(
                    node_id,
                    node_type=NODE_SESSION_SUMMARY,
                    body=body,
                    links=[],
                )
            self._refresh_changed_file(node_id)

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
            total_disk = sum(f.stat().st_size for f in self.memory_dir.rglob("*") if f.is_file())
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

    def changed_since(self, since_unix: int) -> list[dict[str, Any]]:
        """Return MagGraph change-feed entries when available."""
        if not self.available or not hasattr(self._index, "changed_since"):
            return []
        try:
            return [dict(item) for item in self._index.changed_since(since_unix)]
        except Exception:
            return []

    # ─────────────────────────────────────────────
    # Search
    # ─────────────────────────────────────────────

    def search(self, query: str, max_results: int = 10, mode: str = "keyword") -> list[dict[str, Any]]:
        """Search over memory nodes using keyword, semantic, or hybrid mode."""
        if not self.available:
            return []

        if mode in {"semantic", "hybrid"} and self.username:
            semantic = self.semantic_search(query, max_results=max_results, mode=mode)
            if semantic:
                return semantic

        native = self._native_search(query, max_results=max_results)
        if native:
            return native

        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        try:
            for node_id in self._index.list_nodes():
                try:
                    node = self._index.read_node(node_id)
                    if query_lower in node_id.lower() or query_lower in node.body.lower():
                        results.append(
                            {
                                "id": node.id,
                                "type": node.node_type,
                                "snippet": node.body[:200].replace("\n", " "),
                            }
                        )
                        if len(results) >= max_results:
                            break
                except Exception:
                    pass
        except Exception:
            pass

        return results

    def _native_search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Search through MagGraph's structured query API."""
        if not self.available or not hasattr(self._index, "search"):
            return []
        try:
            results = []
            for item in self._index.search(query=query, include_suppressed=False, limit=max_results):
                data = dict(item)
                data.setdefault("type", data.get("node_type", ""))
                data["snippet"] = str(data.get("summary") or "").replace("\n", " ")
                data["reason"] = _search_reason(data)
                with contextlib.suppress(Exception):
                    data["backlinks"] = self._index.backlinks(data["id"])
                results.append(data)
            return results
        except Exception:
            return []

    def semantic_index(self) -> dict[str, Any]:
        """Rebuild/update the semantic sidecar index."""
        if not self.username:
            return {"ok": False, "error": "No username provided"}
        return self._semantic_index().reindex(self._index)

    def semantic_search(
        self, query: str, max_results: int = 10, mode: str = "hybrid"
    ) -> list[dict[str, Any]]:
        """Search the semantic sidecar index. Falls back to keyword search if empty."""
        if not self.username:
            return []
        index = self._semantic_index()
        results = [item.as_dict() for item in index.search(query, top_k=max_results, mode=mode)]
        for item in results:
            item.setdefault("matched", ["semantic"])
            item.setdefault("reason", "semantic sidecar match")
            with contextlib.suppress(Exception):
                item["backlinks"] = self._index.backlinks(item["id"])
        if not results and mode != "keyword":
            return self.search(query, max_results=max_results, mode="keyword")
        return results

    def semantic_status(self) -> dict[str, Any]:
        if not self.username:
            return {"ok": False, "error": "No username provided"}
        return self._semantic_index().status()

    def semantic_reset(self) -> dict[str, Any]:
        if not self.username:
            return {"ok": False, "error": "No username provided"}
        self._semantic_index().reset()
        return self.semantic_status()

    def _semantic_index(self):
        if self._semantic is None:
            from magent.semantic_memory import SemanticMemoryIndex

            self._semantic = SemanticMemoryIndex(
                self.username or "default",
                self.memory_dir,
                provider=self.semantic_provider,
                model=self.semantic_model,
            )
        return self._semantic

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

    def quality_report(self) -> dict[str, Any]:
        """Report duplicate-looking and suppressed memory nodes."""
        nodes = self.export_json()
        body_buckets: dict[str, list[str]] = {}
        suppressed = []
        for node in nodes:
            body = re.sub(r"\s+", " ", node.get("body", "").strip().lower())
            key = body[:240]
            if key:
                body_buckets.setdefault(key, []).append(node["id"])
            if "suppressed: true" in body:
                suppressed.append(node["id"])
        duplicates = [ids for ids in body_buckets.values() if len(ids) > 1]
        return {
            "ok": True,
            "nodes": len(nodes),
            "duplicates": duplicates,
            "suppressed": suppressed,
            "duplicate_groups": len(duplicates),
        }

    def merge_nodes(self, target_id: str, source_id: str) -> dict[str, Any]:
        """Append source body into target and delete source."""
        if self.available and hasattr(self._index, "merge_nodes"):
            try:
                self._index.merge_nodes(target_id, source_id)
                self._refresh_changed_file(target_id)
                return {"ok": True, "target": target_id, "deleted": source_id}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        target = self.read_node(target_id)
        source = self.read_node(source_id)
        if not target or not source or not self.available:
            return {"ok": False, "error": "Target or source node not found"}
        merged_body = (
            target["body"].rstrip()
            + "\n\n## Merged Memory\n\n"
            + source["body"].strip()
            + f"\n\nMerged-from: [[{source_id}]]\n"
        )
        try:
            self._index.update_node(target_id, merged_body)
            self._index.delete_node(source_id)
            return {"ok": True, "target": target_id, "deleted": source_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def merge_preview(self, target_id: str, source_id: str) -> dict[str, Any]:
        """Preview a memory merge without changing the graph."""
        target = self.read_node(target_id)
        source = self.read_node(source_id)
        if not target or not source or not self.available:
            return {"ok": False, "error": "Target or source node not found"}
        merged_body = (
            target["body"].rstrip()
            + "\n\n## Merged Memory\n\n"
            + source["body"].strip()
            + f"\n\nMerged-from: [[{source_id}]]\n"
        )
        return {
            "ok": True,
            "target": target_id,
            "source": source_id,
            "target_chars": len(target["body"]),
            "source_chars": len(source["body"]),
            "merged_chars": len(merged_body),
            "preview": truncate_to_tokens(merged_body, 300),
        }

    def suppress_node(self, node_id: str, reason: str = "") -> dict[str, Any]:
        if self.available and hasattr(self._index, "suppress_node"):
            try:
                self._index.suppress_node(node_id, reason=reason or None)
                self._refresh_changed_file(node_id)
                return {"ok": True, "id": node_id, "reason": reason}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        node = self.read_node(node_id)
        if not node or not self.available:
            return {"ok": False, "error": f"Node not found: {node_id}"}
        body = node["body"].rstrip() + f"\n\nSuppressed: true\nSuppressReason: {reason}\n"
        try:
            self._index.update_node(node_id, body)
            return {"ok": True, "id": node_id, "reason": reason}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def unsuppress_node(self, node_id: str) -> dict[str, Any]:
        if self.available and hasattr(self._index, "unsuppress_node"):
            try:
                self._index.unsuppress_node(node_id)
                self._refresh_changed_file(node_id)
                return {"ok": True, "id": node_id}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        node = self.read_node(node_id)
        if not node or not self.available:
            return {"ok": False, "error": f"Node not found: {node_id}"}
        body = "\n".join(
            line
            for line in node["body"].splitlines()
            if line.strip().lower() != "suppressed: true"
            and not line.strip().lower().startswith("suppressreason:")
        ).rstrip()
        try:
            self._index.update_node(node_id, body + "\n")
            return {"ok": True, "id": node_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def backlinks(self, node_id: str) -> list[str]:
        """Return nodes that link to the given memory node."""
        if not self.available or not hasattr(self._index, "backlinks"):
            return []
        try:
            return list(self._index.backlinks(node_id))
        except Exception:
            return []

    def _memory_kind_for_item(self, item: dict[str, Any]) -> str:
        tags = {str(tag).lower() for tag in item.get("tags", [])}
        node_type = item.get("type", NODE_FACT)
        if "task" in tags:
            return "task"
        if "failure" in tags or "command" in tags or node_type == NODE_ERROR_PATTERN:
            return "tool_failure"
        return MAGGRAPH_MEMORY_KIND_BY_TYPE.get(node_type, "project_fact")

    def _refresh_changed_file(self, node_id: str) -> None:
        """Update a single MagGraph index entry after a write when supported."""
        if not hasattr(self._index, "update_file"):
            return
        node = self.read_node(node_id)
        if not node:
            return
        rel_path = node.get("path") or f"{node_id}.md"
        candidates = [str(rel_path), str(self.memory_dir / str(rel_path))]
        for candidate in candidates:
            with contextlib.suppress(Exception):
                self._index.update_file(candidate)
                return


def _first_sentence_or_line(text: str) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", compact, maxsplit=1)[0]
    return sentence or compact.splitlines()[0]


def _merge_anchor_results(
    semantic_results: list[dict[str, Any]],
    keyword_results: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*semantic_results, *keyword_results]:
        node_id = item.get("id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def _search_reason(item: dict[str, Any]) -> str:
    matched = ", ".join(item.get("matched") or [])
    if matched:
        return f"MagGraph search matched {matched}"
    return "MagGraph search result"
