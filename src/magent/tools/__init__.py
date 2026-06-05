"""Built-in tool registry and executor for MagAgent.

Tools are organized into tiers:
  SILENT (0) - read-only, always auto-approved
  AUTO   (1) - shown, auto-approved in balanced/silent mode
  CONFIRM(2) - requires inline y/n prompt in balanced mode
  BLOCK  (3) - always requires explicit typed confirmation
"""

from __future__ import annotations

import asyncio
import base64
import difflib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.prompt import Confirm

from magent.permissions import (
    RiskTier,
    classify_file_op,
    classify_shell_command,
    check_permission,
)

console = Console()

ToolResult = dict[str, Any]


class ToolExecutor:
    """Executes agent tools with integrated permission checking."""

    def __init__(
        self,
        cwd: str,
        permission_mode: str = "balanced",
        allowed_shell_patterns: list[str] | None = None,
        show_tool_calls: bool = True,
        username: str = "default",
    ):
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.allowed_shell_patterns = allowed_shell_patterns or []
        self.show_tool_calls = show_tool_calls
        self.username = username

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        if self.show_tool_calls and tier > RiskTier.SILENT:
            from magent.permissions import TIER_LABELS
            tier_label = TIER_LABELS.get(tier, str(tier))
            console.print(f"  [dim]🔧 {name}[/dim] [dim cyan][{tier_label}][/dim cyan] [dim]{desc[:80]}[/dim]")

    # ─────────────────────────────────────────────
    # FILE TOOLS
    # ─────────────────────────────────────────────

    async def read_file(self, path: str) -> ToolResult:
        tier = RiskTier.SILENT
        self._log_tool("read_file", path, tier)
        abs_path = Path(self.cwd) / path
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "content": content, "path": str(abs_path), "lines": len(content.splitlines())}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def write_file(self, path: str, content: str) -> ToolResult:
        tier = classify_file_op("write", path, self.cwd)
        abs_path = Path(self.cwd) / path
        self._log_tool("write_file", str(abs_path), tier)
        perm = check_permission(f"Write {len(content)} chars to {abs_path}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(abs_path), "bytes": len(content.encode())}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def edit_file(self, path: str, old_str: str, new_str: str) -> ToolResult:
        tier = classify_file_op("edit", path, self.cwd)
        abs_path = Path(self.cwd) / path
        self._log_tool("edit_file", str(abs_path), tier)
        perm = check_permission(f"Edit {abs_path}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}
        try:
            content = abs_path.read_text(encoding="utf-8")
            if old_str not in content:
                return {"ok": False, "error": f"String not found in {path}"}
            abs_path.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
            return {"ok": True, "path": str(abs_path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def delete_file(self, path: str) -> ToolResult:
        tier = classify_file_op("delete", path, self.cwd)
        abs_path = Path(self.cwd) / path
        self._log_tool("delete_file", str(abs_path), tier)
        perm = check_permission(f"Delete {abs_path}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}
        try:
            if abs_path.is_dir():
                shutil.rmtree(abs_path)
            else:
                abs_path.unlink()
            return {"ok": True, "path": str(abs_path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def list_dir(self, path: str = ".") -> ToolResult:
        abs_path = Path(self.cwd) / path
        try:
            entries = []
            for item in sorted(abs_path.iterdir()):
                entries.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                })
            return {"ok": True, "path": str(abs_path), "entries": entries, "count": len(entries)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def diff_files(self, path_a: str, path_b: str) -> ToolResult:
        """Unified diff between two files."""
        self._log_tool("diff_files", f"{path_a} vs {path_b}", RiskTier.SILENT)
        try:
            a = (Path(self.cwd) / path_a).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            b = (Path(self.cwd) / path_b).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            diff = list(difflib.unified_diff(a, b, fromfile=path_a, tofile=path_b))
            return {"ok": True, "diff": "".join(diff), "changed": bool(diff)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def compress(self, source_path: str, output_path: str, format: str = "zip") -> ToolResult:
        """Compress a file or directory into zip or tar.gz."""
        tier = RiskTier.AUTO
        self._log_tool("compress", f"{source_path} → {output_path}", tier)
        perm = check_permission(f"Compress {source_path} → {output_path}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}
        try:
            src = Path(self.cwd) / source_path
            out = Path(self.cwd) / output_path
            if format == "zip":
                with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                    if src.is_dir():
                        for f in src.rglob("*"):
                            if f.is_file():
                                zf.write(f, f.relative_to(src.parent))
                    else:
                        zf.write(src, src.name)
            else:
                import tarfile
                mode = "w:gz" if format == "tar.gz" else "w:bz2"
                with tarfile.open(out, mode) as tf:
                    tf.add(src, arcname=src.name)
            return {"ok": True, "output": str(out), "size_bytes": out.stat().st_size}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def extract(self, archive_path: str, output_dir: str = ".") -> ToolResult:
        """Extract a zip or tar archive."""
        tier = RiskTier.AUTO
        self._log_tool("extract", archive_path, tier)
        perm = check_permission(f"Extract {archive_path}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}
        try:
            src = Path(self.cwd) / archive_path
            out = Path(self.cwd) / output_dir
            out.mkdir(parents=True, exist_ok=True)
            if archive_path.endswith(".zip"):
                with zipfile.ZipFile(src) as zf:
                    zf.extractall(out)
                    names = zf.namelist()
            else:
                import tarfile
                with tarfile.open(src) as tf:
                    tf.extractall(out)
                    names = tf.getnames()
            return {"ok": True, "output_dir": str(out), "extracted": len(names), "files": names[:20]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─────────────────────────────────────────────
    # SHELL & CODE TOOLS
    # ─────────────────────────────────────────────

    async def run_shell(self, command: str, timeout: int = 60) -> ToolResult:
        tier = classify_shell_command(command, self.allowed_shell_patterns)
        self._log_tool("run_shell", command, tier)
        perm = check_permission(f"Run: `{command}`", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}
        try:
            proc = await asyncio.create_subprocess_shell(
                command, cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return {"ok": False, "error": f"Command timed out after {timeout}s"}
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def run_python(self, code: str, timeout: int = 30) -> ToolResult:
        """Execute Python code in an isolated subprocess and capture output."""
        tier = RiskTier.CONFIRM
        self._log_tool("run_python", f"{len(code)} chars of Python", tier)
        perm = check_permission("Execute Python code snippet", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                tmp_path = f.name
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return {"ok": False, "error": f"Python execution timed out after {timeout}s"}
            finally:
                Path(tmp_path).unlink(missing_ok=True)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace")[:8000],
                "stderr": stderr.decode("utf-8", errors="replace")[:2000],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def install_package(self, package: str, version: str = "") -> ToolResult:
        """
        Install a Python package via pip, asking user permission first.
        Use this when a task requires an optional dependency (moviepy, pandas, etc).
        """
        tier = RiskTier.CONFIRM
        pkg_spec = f"{package}=={version}" if version else package
        self._log_tool("install_package", pkg_spec, tier)

        # Check if already installed
        if importlib.util.find_spec(package.replace("-", "_").split("[")[0]) is not None:
            return {"ok": True, "already_installed": True, "package": pkg_spec}

        perm = check_permission(
            f"pip install {pkg_spec}  (required for this task)",
            tier,
            self.permission_mode,
        )
        if not perm.approved:
            return {"ok": False, "error": f"User declined to install {pkg_spec}"}

        result = await self.run_shell(
            f"{sys.executable} -m pip install {pkg_spec} --quiet",
            timeout=120,
        )
        if result["ok"]:
            return {"ok": True, "installed": pkg_spec, "already_installed": False}
        return {"ok": False, "error": result.get("stderr", "pip failed"), "package": pkg_spec}

    # ─────────────────────────────────────────────
    # WEB TOOLS
    # ─────────────────────────────────────────────

    async def search_codebase(self, pattern: str, path: str = ".") -> ToolResult:
        self._log_tool("search_codebase", f"{pattern!r} in {path}", RiskTier.SILENT)
        abs_path = Path(self.cwd) / path
        rg = shutil.which("rg") or shutil.which("grep")
        if not rg:
            return {"ok": False, "error": "No search tool found (rg or grep)"}
        cmd = ["rg", "--line-number", "--no-heading", pattern, str(abs_path)] \
            if shutil.which("rg") else ["grep", "-rn", pattern, str(abs_path)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            return {"ok": True, "matches": lines[:100], "truncated": len(lines) > 100, "total": len(lines)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def web_search(self, query: str, max_results: int = 8) -> ToolResult:
        """Search the web using DuckDuckGo (no API key required, real results)."""
        tier = RiskTier.AUTO
        self._log_tool("web_search", query, tier)
        perm = check_permission(f"Web search: {query}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}

        # Try duckduckgo-search first (real results)
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
            results = [
                {"title": r.get("title", ""), "snippet": r.get("body", ""), "url": r.get("href", "")}
                for r in raw
            ]
            return {"ok": True, "query": query, "results": results, "source": "duckduckgo-search"}
        except Exception as ddgs_err:
            pass

        # Fallback: DDG instant answer API
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1"},
                )
                data = resp.json()
                results = []
                if data.get("AbstractText"):
                    results.append({
                        "title": data.get("Heading", query),
                        "snippet": data.get("AbstractText"),
                        "url": data.get("AbstractURL"),
                    })
                for r in data.get("RelatedTopics", [])[:6]:
                    if isinstance(r, dict) and r.get("Text"):
                        results.append({
                            "title": r.get("Text", "")[:80],
                            "snippet": r.get("Text"),
                            "url": r.get("FirstURL"),
                        })
                return {"ok": True, "query": query, "results": results, "source": "ddg-instant"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def web_fetch(self, url: str, extract_article: bool = True) -> ToolResult:
        """
        Fetch and read a URL. Uses trafilatura for clean article extraction
        when extract_article=True (default), otherwise strips HTML tags.
        """
        tier = RiskTier.AUTO
        self._log_tool("web_fetch", url, tier)
        perm = check_permission(f"Fetch URL: {url}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}

        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "MagAgent/0.2"})
                raw_html = resp.text

            # Try trafilatura for clean article text
            if extract_article:
                try:
                    import trafilatura
                    text = trafilatura.extract(raw_html, include_comments=False, include_tables=True) or ""
                    if text and len(text) > 200:
                        return {
                            "ok": True, "url": str(resp.url), "status": resp.status_code,
                            "content": text[:10000], "truncated": len(text) > 10000,
                            "extractor": "trafilatura",
                        }
                except ImportError:
                    pass

            # Fallback: regex strip HTML
            import re
            text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return {
                "ok": True, "url": str(resp.url), "status": resp.status_code,
                "content": text[:8000], "truncated": len(text) > 8000,
                "extractor": "html-strip",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def http_request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        body: str | dict | None = None,
        timeout: int = 30,
    ) -> ToolResult:
        """Full HTTP client: GET/POST/PUT/PATCH/DELETE with custom headers and body."""
        tier = RiskTier.AUTO
        self._log_tool("http_request", f"{method.upper()} {url}", tier)
        perm = check_permission(f"HTTP {method.upper()} {url}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}
        try:
            kwargs: dict[str, Any] = {"headers": headers or {}, "timeout": timeout, "follow_redirects": True}
            if body:
                if isinstance(body, dict):
                    kwargs["json"] = body
                else:
                    kwargs["content"] = body.encode() if isinstance(body, str) else body
            async with httpx.AsyncClient() as client:
                resp = await client.request(method.upper(), url, **kwargs)
            try:
                data = resp.json()
            except Exception:
                data = None
            return {
                "ok": resp.is_success,
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body_text": resp.text[:5000],
                "body_json": data,
                "truncated": len(resp.text) > 5000,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─────────────────────────────────────────────
    # DATA TOOLS
    # ─────────────────────────────────────────────

    async def json_query(self, path_or_json: str, query: str) -> ToolResult:
        """
        Run a JMESPath query over a JSON file (if path exists) or a JSON string.
        Example: json_query("data.json", "items[?status=='active'].name")
        """
        self._log_tool("json_query", f"{query!r}", RiskTier.SILENT)
        try:
            import jmespath
            # Decide if it's a file path or raw JSON
            candidate = Path(self.cwd) / path_or_json
            if candidate.exists():
                data = json.loads(candidate.read_text())
            else:
                data = json.loads(path_or_json)
            result = jmespath.search(query, data)
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─────────────────────────────────────────────
    # SYSTEM TOOLS
    # ─────────────────────────────────────────────

    async def system_info(self) -> ToolResult:
        """Get CPU, RAM, disk usage, OS info, and Python version."""
        self._log_tool("system_info", "fetching system metrics", RiskTier.SILENT)
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage(self.cwd)
            return {
                "ok": True,
                "cpu_percent": cpu,
                "ram_total_gb": round(ram.total / 1e9, 2),
                "ram_used_gb": round(ram.used / 1e9, 2),
                "ram_percent": ram.percent,
                "disk_total_gb": round(disk.total / 1e9, 2),
                "disk_used_gb": round(disk.used / 1e9, 2),
                "disk_free_gb": round(disk.free / 1e9, 2),
                "platform": sys.platform,
                "python": sys.version.split()[0],
                "cwd": self.cwd,
            }
        except ImportError:
            return {"ok": False, "error": "psutil not installed. Use install_package('psutil')."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def notify(self, title: str, message: str, urgency: str = "normal") -> ToolResult:
        """Send a desktop notification to alert the user when a long task completes."""
        self._log_tool("notify", title, RiskTier.SILENT)
        try:
            from plyer import notification
            notification.notify(title=title, message=message, timeout=8)
            return {"ok": True, "title": title, "message": message}
        except ImportError:
            pass
        # Fallback to notify-send
        if shutil.which("notify-send"):
            result = await self.run_shell(
                f'notify-send --urgency={urgency} {json.dumps(title)} {json.dumps(message)}'
            )
            return result
        return {"ok": False, "error": "No notification backend available (plyer or notify-send)"}

    async def clipboard_read(self) -> ToolResult:
        """Read the current system clipboard contents."""
        self._log_tool("clipboard_read", "reading clipboard", RiskTier.SILENT)
        try:
            import pyperclip
            text = pyperclip.paste()
            return {"ok": True, "content": text, "length": len(text)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def clipboard_write(self, text: str) -> ToolResult:
        """Write text to the system clipboard."""
        tier = RiskTier.AUTO
        self._log_tool("clipboard_write", f"{len(text)} chars", tier)
        perm = check_permission(f"Write {len(text)} chars to clipboard", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}
        try:
            import pyperclip
            pyperclip.copy(text)
            return {"ok": True, "length": len(text)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def open_file(self, path: str) -> ToolResult:
        """Open a file in its default application (xdg-open on Linux)."""
        tier = RiskTier.AUTO
        self._log_tool("open_file", path, tier)
        perm = check_permission(f"Open file: {path}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}
        abs_path = str(Path(self.cwd) / path)
        opener = shutil.which("xdg-open") or shutil.which("open")
        if not opener:
            return {"ok": False, "error": "No file opener found (xdg-open / open)"}
        result = await self.run_shell(f"{opener} {json.dumps(abs_path)}")
        return result

    async def read_image(self, path: str) -> ToolResult:
        """Read image metadata and return base64-encoded content for vision models."""
        self._log_tool("read_image", path, RiskTier.SILENT)
        try:
            from PIL import Image
            abs_path = Path(self.cwd) / path
            with Image.open(abs_path) as img:
                meta = {
                    "format": img.format,
                    "mode": img.mode,
                    "size": img.size,
                    "width": img.size[0],
                    "height": img.size[1],
                }
                # Resize for embedding if large
                if img.size[0] > 1024 or img.size[1] > 1024:
                    img.thumbnail((1024, 1024))
                buf = io.BytesIO()
                img.save(buf, format=img.format or "PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            return {"ok": True, "metadata": meta, "base64": b64, "path": str(abs_path)}
        except ImportError:
            return {"ok": False, "error": "Pillow not installed. Use install_package('Pillow')."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ─────────────────────────────────────────────
    # DATABASE TOOLS (SQLite)
    # ─────────────────────────────────────────────

    async def db_query(self, sql: str, params: list | None = None, db_name: str = "default") -> ToolResult:
        """SELECT from a named user database. Use db_name to target a specific database."""
        self._log_tool("db_query", f"[{db_name}] {sql[:60]}", RiskTier.SILENT)
        from magent.tools.db import db_query
        return db_query(self.username, sql, params, db_name)

    async def db_execute(self, sql: str, params: list | None = None, db_name: str = "default") -> ToolResult:
        """INSERT/UPDATE/DELETE/CREATE TABLE in a named user database."""
        tier = RiskTier.AUTO
        self._log_tool("db_execute", f"[{db_name}] {sql[:60]}", tier)
        perm = check_permission(f"DB write [{db_name}]: {sql[:60]}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied"}
        from magent.tools.db import db_execute
        return db_execute(self.username, sql, params, db_name)

    async def db_list_tables(self, db_name: str = "default") -> ToolResult:
        """List tables and row counts in a named user database."""
        self._log_tool("db_list_tables", db_name, RiskTier.SILENT)
        from magent.tools.db import db_list_tables
        return db_list_tables(self.username, db_name)

    async def db_schema(self, table: str, db_name: str = "default") -> ToolResult:
        """Show schema (columns, types) for a table in a named database."""
        self._log_tool("db_schema", f"[{db_name}].{table}", RiskTier.SILENT)
        from magent.tools.db import db_schema
        return db_schema(self.username, table, db_name)

    async def db_list_databases(self) -> ToolResult:
        """List all databases created for the current user."""
        self._log_tool("db_list_databases", self.username, RiskTier.SILENT)
        from magent.tools.db import list_databases
        return list_databases(self.username)

    # ─────────────────────────────────────────────
    # GIT TOOLS
    # ─────────────────────────────────────────────

    async def git_op(self, subcommand: str, *args: str) -> ToolResult:
        cmd = f"git {subcommand} {' '.join(args)}"
        return await self.run_shell(cmd)

    # ─────────────────────────────────────────────
    # TOOL DEFINITIONS (OpenAI function-calling format)
    # ─────────────────────────────────────────────

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            _def("read_file", "Read the contents of a file.", {"path": ("string", "Relative file path")}),
            _def("write_file", "Write content to a file (creates or overwrites).",
                 {"path": ("string", "File path"), "content": ("string", "Full file content")}),
            _def("edit_file", "Replace an exact string in a file.",
                 {"path": ("string", None), "old_str": ("string", "Exact string to replace"),
                  "new_str": ("string", "Replacement string")}),
            _def("delete_file", "Delete a file or directory.", {"path": ("string", None)}),
            _def("list_dir", "List contents of a directory.", {"path": ("string", "Path (default: .)")}),
            _def("diff_files", "Show unified diff between two files.",
                 {"path_a": ("string", "First file"), "path_b": ("string", "Second file")}),
            _def("compress", "Compress a file or directory to zip or tar.gz.",
                 {"source_path": ("string", None), "output_path": ("string", None),
                  "format": ("string", "zip or tar.gz (default: zip)")}),
            _def("extract", "Extract a zip or tar archive.",
                 {"archive_path": ("string", None), "output_dir": ("string", "Where to extract (default: .)")}),
            _def("run_shell", "Run a shell command in the project directory.",
                 {"command": ("string", None), "timeout": ("integer", "Seconds (default 60)")}),
            _def("run_python", "Execute Python code in an isolated subprocess and return stdout/stderr.",
                 {"code": ("string", "Python code to run"), "timeout": ("integer", "Seconds (default 30)")}),
            _def("install_package", "Install a Python package via pip (asks user permission first).",
                 {"package": ("string", "Package name e.g. moviepy"), "version": ("string", "Optional pinned version")}),
            _def("search_codebase", "Search for a pattern in the codebase using ripgrep.",
                 {"pattern": ("string", None), "path": ("string", "Directory (default: .)")}),
            _def("web_search", "Search the web using DuckDuckGo (real results, no API key).",
                 {"query": ("string", None), "max_results": ("integer", "Number of results (default 8)")}),
            _def("web_fetch", "Fetch a URL and return clean article text using trafilatura.",
                 {"url": ("string", None), "extract_article": ("boolean", "Use trafilatura for clean text (default true)")}),
            _def("http_request", "Make any HTTP request (GET/POST/PUT/PATCH/DELETE) with custom headers and body.",
                 {"method": ("string", "GET POST PUT PATCH DELETE"),
                  "url": ("string", None),
                  "headers": ("object", "Optional headers dict"),
                  "body": ("string", "Optional body (string or JSON string)"),
                  "timeout": ("integer", "Seconds (default 30)")}),
            _def("json_query", "Run a JMESPath query over a JSON file or JSON string.",
                 {"path_or_json": ("string", "File path or raw JSON string"),
                  "query": ("string", "JMESPath expression e.g. items[?active].name")}),
            _def("system_info", "Get CPU, RAM, disk usage, OS info, and Python version.", {}),
            _def("notify", "Send a desktop notification to alert the user.",
                 {"title": ("string", None), "message": ("string", None), "urgency": ("string", "low/normal/critical")}),
            _def("clipboard_read", "Read the current system clipboard contents.", {}),
            _def("clipboard_write", "Write text to the system clipboard.",
                 {"text": ("string", None)}),
            _def("open_file", "Open a file in its default application.",
                 {"path": ("string", None)}),
            _def("read_image", "Read image metadata and base64 encode it for vision models.",
                 {"path": ("string", None)}),
            _def("db_query", "SELECT from a named SQLite database.",
                 {"sql": ("string", "SELECT statement"),
                  "params": ("array", "Optional parameter list"),
                  "db_name": ("string", "Database name (default, project name, or custom)")}),
            _def("db_execute", "INSERT/UPDATE/DELETE/CREATE TABLE in a named SQLite database.",
                 {"sql": ("string", "SQL statement"),
                  "params": ("array", "Optional parameter list"),
                  "db_name": ("string", "Database name")}),
            _def("db_list_tables", "List tables in a named SQLite database.",
                 {"db_name": ("string", "Database name (default: 'default')")}),
            _def("db_schema", "Show columns and types for a table.",
                 {"table": ("string", None), "db_name": ("string", "Database name")}),
            _def("db_list_databases", "List all SQLite databases created for the current user.", {}),
            _def("git_op", "Run a git subcommand.",
                 {"subcommand": ("string", "e.g. status, diff, add -A, commit -m 'msg'"),
                  "args": ("array", "Optional extra args")}),
        ]

    async def dispatch(self, tool_name: str, tool_args: dict[str, Any]) -> ToolResult:
        """Dispatch a tool call by name."""
        a = tool_args
        dispatch_map: dict[str, Any] = {
            "read_file":        lambda: self.read_file(a["path"]),
            "write_file":       lambda: self.write_file(a["path"], a["content"]),
            "edit_file":        lambda: self.edit_file(a["path"], a["old_str"], a["new_str"]),
            "delete_file":      lambda: self.delete_file(a["path"]),
            "list_dir":         lambda: self.list_dir(a.get("path", ".")),
            "diff_files":       lambda: self.diff_files(a["path_a"], a["path_b"]),
            "compress":         lambda: self.compress(a["source_path"], a["output_path"], a.get("format", "zip")),
            "extract":          lambda: self.extract(a["archive_path"], a.get("output_dir", ".")),
            "run_shell":        lambda: self.run_shell(a["command"], a.get("timeout", 60)),
            "run_python":       lambda: self.run_python(a["code"], a.get("timeout", 30)),
            "install_package":  lambda: self.install_package(a["package"], a.get("version", "")),
            "search_codebase":  lambda: self.search_codebase(a["pattern"], a.get("path", ".")),
            "web_search":       lambda: self.web_search(a["query"], a.get("max_results", 8)),
            "web_fetch":        lambda: self.web_fetch(a["url"], a.get("extract_article", True)),
            "http_request":     lambda: self.http_request(a["method"], a["url"], a.get("headers"), a.get("body"), a.get("timeout", 30)),
            "json_query":       lambda: self.json_query(a["path_or_json"], a["query"]),
            "system_info":      lambda: self.system_info(),
            "notify":           lambda: self.notify(a["title"], a["message"], a.get("urgency", "normal")),
            "clipboard_read":   lambda: self.clipboard_read(),
            "clipboard_write":  lambda: self.clipboard_write(a["text"]),
            "open_file":        lambda: self.open_file(a["path"]),
            "read_image":       lambda: self.read_image(a["path"]),
            "db_query":         lambda: self.db_query(a["sql"], a.get("params"), a.get("db_name", "default")),
            "db_execute":       lambda: self.db_execute(a["sql"], a.get("params"), a.get("db_name", "default")),
            "db_list_tables":   lambda: self.db_list_tables(a.get("db_name", "default")),
            "db_schema":        lambda: self.db_schema(a["table"], a.get("db_name", "default")),
            "db_list_databases":lambda: self.db_list_databases(),
            "git_op":           lambda: self.git_op(a["subcommand"], *a.get("args", [])),
        }
        fn = dispatch_map.get(tool_name)
        if fn is None:
            return {"ok": False, "error": f"Unknown tool: {tool_name}"}
        return await fn()


# ─────────────────────────────────────────────
# Helper: compact tool definition builder
# ─────────────────────────────────────────────

def _def(name: str, description: str, params: dict[str, tuple[str, str | None]]) -> dict[str, Any]:
    """Build an OpenAI-compatible tool definition."""
    properties: dict[str, Any] = {}
    for param_name, (param_type, param_desc) in params.items():
        prop: dict[str, Any] = {"type": param_type}
        if param_desc:
            prop["description"] = param_desc
        properties[param_name] = prop

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [],
            },
        },
    }
