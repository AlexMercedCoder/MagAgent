"""File, directory, diff, documentation, and archive capability tools."""

from __future__ import annotations

import ast
import difflib
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Literal

from magent.permissions import PermissionResult, RiskTier
from magent.tools.archive import safe_extract_tar, safe_extract_zip
from magent.tools.types import READ_FILE_PREVIEW_CHARS, ToolResult


def _suspicious_write_file_content(path: str, content: str) -> str:
    """Return a reason when a write payload is obviously not file content."""
    stripped = (content or "").strip()
    if not stripped:
        return "content is empty"

    target = Path(path)
    path_tokens = {target.name.lower(), str(target).lower()}
    if stripped.lower() in path_tokens:
        return "content is only the target filename/path"

    suffix = target.suffix.lower()
    if suffix in {".html", ".htm"}:
        lower = stripped.lower()
        if len(stripped) < 80 and not any(
            token in lower for token in ("<html", "<!doctype", "<body", "<section")
        ):
            return "HTML file content is too short and does not look like markup"
    if suffix in {".md", ".markdown"} and len(stripped) < 20 and stripped.lower() == target.stem.lower():
        return "Markdown file content is only the target title"
    return ""


class FileToolsMixin:
    """File/archive capability implementation mixed into the tool executor."""

    def _path_tier(self, op: str, path: str) -> tuple[Path, RiskTier]:
        raise NotImplementedError

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        raise NotImplementedError

    def _check_permission(self, action_description: str, tier: RiskTier) -> PermissionResult:
        raise NotImplementedError

    def _permission_denied(self, perm: PermissionResult) -> ToolResult:
        raise NotImplementedError

    def _checkpoint(self, abs_path: Path, operation: str) -> str:
        raise NotImplementedError

    async def read_file(self, path: str) -> ToolResult:
        abs_path, tier = self._path_tier("read", path)
        self._log_tool("read_file", str(abs_path), tier)
        perm = self._check_permission(f"Read {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            total_lines = len(content.splitlines())
            truncated = len(content) > READ_FILE_PREVIEW_CHARS
            if truncated:
                content = (
                    content[:READ_FILE_PREVIEW_CHARS].rstrip()
                    + "\n\n[...file preview truncated; use outline_file or read_file_range...]"
                )
            return {
                "ok": True,
                "content": content,
                "path": str(abs_path),
                "lines": total_lines,
                "truncated": truncated,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def read_file_range(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> ToolResult:
        """Read a 1-based inclusive line range from a file."""
        abs_path, tier = self._path_tier("read", path)
        self._log_tool("read_file_range", f"{abs_path}:{start_line}-{end_line or ''}", tier)
        perm = self._check_permission(f"Read {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(start_line, 1)
            end = end_line if end_line is not None else min(start + 199, len(lines))
            end = max(start, min(end, len(lines)))
            selected = lines[start - 1 : end]
            numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start=start))
            return {
                "ok": True,
                "path": str(abs_path),
                "start_line": start,
                "end_line": end,
                "total_lines": len(lines),
                "content": numbered,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def outline_file(self, path: str, max_symbols: int = 200) -> ToolResult:
        """Return a compact structural outline for a source file."""
        abs_path, tier = self._path_tier("read", path)
        self._log_tool("outline_file", str(abs_path), tier)
        perm = self._check_permission(f"Outline {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            symbols: list[dict[str, Any]] = []
            if abs_path.suffix.lower() == ".py":
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        symbols.append(
                            {
                                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                                "name": node.name,
                                "line": node.lineno,
                            }
                        )
            else:
                pattern = re.compile(
                    r"^\s*(class|function|def|async def|export function|const|let|var)\s+([A-Za-z_][\w$]*)"
                )
                for lineno, line in enumerate(lines, start=1):
                    match = pattern.match(line)
                    if match:
                        symbols.append(
                            {"kind": match.group(1).strip(), "name": match.group(2), "line": lineno}
                        )
            symbols.sort(key=lambda item: item["line"])
            return {
                "ok": True,
                "path": str(abs_path),
                "lines": len(lines),
                "symbols": symbols[:max_symbols],
                "truncated": len(symbols) > max_symbols,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def write_file(self, path: str, content: str) -> ToolResult:
        abs_path, tier = self._path_tier("write", path)
        self._log_tool("write_file", str(abs_path), tier)
        suspicious_reason = _suspicious_write_file_content(path, content)
        if suspicious_reason:
            return {
                "ok": False,
                "error": (
                    f"Refused suspicious write_file payload: {suspicious_reason}. "
                    "Call write_file again with the complete intended file contents."
                ),
                "blocked_by": "write-file-content-guard",
                "path": str(abs_path),
                "bytes": len((content or "").encode()),
            }
        perm = self._check_permission(f"Write {len(content)} chars to {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            if abs_path.exists() and abs_path.is_file():
                existing = abs_path.read_text(encoding="utf-8", errors="replace")
                if existing == content:
                    return {
                        "ok": True,
                        "path": str(abs_path),
                        "bytes": len(content.encode()),
                        "unchanged": True,
                    }
            checkpoint_id = self._checkpoint(abs_path, "write_file")
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            return {
                "ok": True,
                "path": str(abs_path),
                "bytes": len(content.encode()),
                "checkpoint_id": checkpoint_id,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def edit_file(self, path: str, old_str: str, new_str: str) -> ToolResult:
        abs_path, tier = self._path_tier("edit", path)
        self._log_tool("edit_file", str(abs_path), tier)
        perm = self._check_permission(f"Edit {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            # errors="replace" so a non-UTF-8 file reports a readable failure
            # instead of raising out of the tool.
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            occurrences = content.count(old_str)
            if occurrences == 0:
                return {"ok": False, "error": f"String not found in {path}"}
            if occurrences > 1:
                # Editing an arbitrary one of several matches and reporting
                # success is worse than refusing: the caller cannot tell which
                # site changed.
                return {
                    "ok": False,
                    "error": (
                        f"old_str matches {occurrences} places in {path}; include more "
                        "surrounding context so the intended one is unambiguous."
                    ),
                    "occurrences": occurrences,
                }
            checkpoint_id = self._checkpoint(abs_path, "edit_file")
            abs_path.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
            return {"ok": True, "path": str(abs_path), "checkpoint_id": checkpoint_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def delete_file(self, path: str) -> ToolResult:
        abs_path, tier = self._path_tier("delete", path)
        self._log_tool("delete_file", str(abs_path), tier)
        perm = self._check_permission(f"Delete {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            checkpoint_id = self._checkpoint(abs_path, "delete_file")
            if abs_path.is_dir():
                shutil.rmtree(abs_path)
            else:
                abs_path.unlink()
            return {"ok": True, "path": str(abs_path), "checkpoint_id": checkpoint_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def magent_docs_search(self, query: str, limit: int = 5) -> ToolResult:
        """Search MagAgent's built-in documentation."""
        from magent.docs import search_docs

        return {"ok": True, "query": query, "results": search_docs(query, limit=limit)}

    async def list_dir(self, path: str = ".") -> ToolResult:
        abs_path, tier = self._path_tier("read", path)
        self._log_tool("list_dir", str(abs_path), tier)
        perm = self._check_permission(f"List {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            entries = []
            for item in sorted(abs_path.iterdir()):
                entries.append(
                    {
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                    }
                )
            return {"ok": True, "path": str(abs_path), "entries": entries, "count": len(entries)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def diff_files(self, path_a: str, path_b: str) -> ToolResult:
        """Return a unified diff between two files."""
        abs_a, tier_a = self._path_tier("read", path_a)
        abs_b, tier_b = self._path_tier("read", path_b)
        tier = max(tier_a, tier_b)
        self._log_tool("diff_files", f"{abs_a} vs {abs_b}", tier)
        perm = self._check_permission(f"Diff {abs_a} and {abs_b}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            a = abs_a.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            b = abs_b.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            diff = list(difflib.unified_diff(a, b, fromfile=path_a, tofile=path_b))
            return {"ok": True, "diff": "".join(diff), "changed": bool(diff)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def compress(self, source_path: str, output_path: str, format: str = "zip") -> ToolResult:
        """Compress a file or directory into zip, tar.gz, or tar.bz2."""
        src, src_tier = self._path_tier("read", source_path)
        out, out_tier = self._path_tier("write", output_path)
        tier = max(RiskTier.AUTO, src_tier, out_tier)
        self._log_tool("compress", f"{source_path} \u2192 {output_path}", tier)
        perm = self._check_permission(f"Compress {src} \u2192 {out}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            if format == "zip":
                with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
                    if src.is_dir():
                        for item in src.rglob("*"):
                            if item.is_file():
                                archive.write(item, item.relative_to(src.parent))
                    else:
                        archive.write(src, src.name)
            else:
                import tarfile

                mode: Literal["w:gz", "w:bz2"] = "w:gz" if format == "tar.gz" else "w:bz2"
                with tarfile.open(out, mode) as archive:
                    archive.add(src, arcname=src.name)
            return {"ok": True, "output": str(out), "size_bytes": out.stat().st_size}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def extract(self, archive_path: str, output_dir: str = ".") -> ToolResult:
        """Safely extract a zip or tar archive."""
        src, src_tier = self._path_tier("read", archive_path)
        out, out_tier = self._path_tier("write", output_dir)
        tier = max(RiskTier.AUTO, src_tier, out_tier)
        self._log_tool("extract", archive_path, tier)
        perm = self._check_permission(f"Extract {src} to {out}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            out.mkdir(parents=True, exist_ok=True)
            if archive_path.lower().endswith(".zip"):
                with zipfile.ZipFile(src) as archive:
                    names = archive.namelist()
                    safe_extract_zip(archive, out)
            else:
                import tarfile

                with tarfile.open(src) as archive:
                    names = archive.getnames()
                    safe_extract_tar(archive, out)
            return {
                "ok": True,
                "output_dir": str(out),
                "extracted": len(names),
                "files": names[:20],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
