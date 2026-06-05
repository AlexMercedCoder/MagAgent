"""Built-in tool registry and executor for MagAgent."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from magent.permissions import (
    RiskTier,
    classify_file_op,
    classify_shell_command,
    check_permission,
)

console = Console()

# Tool result type
ToolResult = dict[str, Any]


class ToolExecutor:
    """Executes agent tools with integrated permission checking."""

    def __init__(
        self,
        cwd: str,
        permission_mode: str = "balanced",
        allowed_shell_patterns: list[str] | None = None,
        show_tool_calls: bool = True,
    ):
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.allowed_shell_patterns = allowed_shell_patterns or []
        self.show_tool_calls = show_tool_calls

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        if self.show_tool_calls and tier > RiskTier.SILENT:
            from magent.permissions import TIER_LABELS
            tier_label = TIER_LABELS.get(tier, str(tier))
            console.print(f"  [dim]🔧 {name}[/dim] [{tier_label}] [dim]{desc}[/dim]")

    async def read_file(self, path: str) -> ToolResult:
        tier = RiskTier.SILENT
        self._log_tool("read_file", path, tier)
        abs_path = Path(self.cwd) / path
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "content": content, "path": str(abs_path)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def write_file(self, path: str, content: str) -> ToolResult:
        tier = classify_file_op("write", path, self.cwd)
        abs_path = Path(self.cwd) / path
        action_desc = f"Write {len(content)} chars to {abs_path}"
        self._log_tool("write_file", str(abs_path), tier)

        perm = check_permission(action_desc, tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}

        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(abs_path), "bytes": len(content)}
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
            new_content = content.replace(old_str, new_str, 1)
            abs_path.write_text(new_content, encoding="utf-8")
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
        tier = RiskTier.SILENT
        abs_path = Path(self.cwd) / path
        try:
            entries = []
            for item in sorted(abs_path.iterdir()):
                entries.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                })
            return {"ok": True, "path": str(abs_path), "entries": entries}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def run_shell(self, command: str, timeout: int = 60) -> ToolResult:
        tier = classify_shell_command(command, self.allowed_shell_patterns)
        self._log_tool("run_shell", command, tier)

        perm = check_permission(f"Run: `{command}`", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
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

    async def search_codebase(self, pattern: str, path: str = ".") -> ToolResult:
        tier = RiskTier.SILENT
        self._log_tool("search_codebase", f"{pattern!r} in {path}", tier)
        abs_path = Path(self.cwd) / path

        # Try ripgrep first, fall back to grep
        rg = shutil.which("rg") or shutil.which("grep")
        if not rg:
            return {"ok": False, "error": "No search tool found (rg or grep)"}

        cmd = ["rg", "--line-number", "--no-heading", pattern, str(abs_path)] \
            if shutil.which("rg") else \
            ["grep", "-rn", pattern, str(abs_path)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            return {"ok": True, "matches": lines[:100], "truncated": len(lines) > 100}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def web_search(self, query: str) -> ToolResult:
        tier = RiskTier.AUTO
        self._log_tool("web_search", query, tier)

        perm = check_permission(f"Web search: {query}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}

        # Use DuckDuckGo instant answer API (no key required)
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
                for r in data.get("RelatedTopics", [])[:5]:
                    if isinstance(r, dict) and r.get("Text"):
                        results.append({
                            "title": r.get("Text", "")[:80],
                            "snippet": r.get("Text"),
                            "url": r.get("FirstURL"),
                        })
                return {"ok": True, "query": query, "results": results}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def web_fetch(self, url: str) -> ToolResult:
        tier = RiskTier.AUTO
        self._log_tool("web_fetch", url, tier)

        perm = check_permission(f"Fetch URL: {url}", tier, self.permission_mode)
        if not perm.approved:
            return {"ok": False, "error": "Permission denied by user"}

        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "MagAgent/0.1"})
                # Strip HTML tags for readability
                import re
                text = resp.text
                text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", "", text)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
                return {
                    "ok": True,
                    "url": str(resp.url),
                    "status": resp.status_code,
                    "content": text[:8000],
                    "truncated": len(text) > 8000,
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def git_op(self, subcommand: str, *args: str) -> ToolResult:
        cmd = f"git {subcommand} {' '.join(args)}"
        return await self.run_shell(cmd)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool definitions for all built-in tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the contents of a file. Path is relative to the project root.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "Relative file path"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file (creates or overwrites). Path relative to project root.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string", "description": "Full file content to write"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": "Replace an exact string in a file with a new string. Fails if old_str not found.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "old_str": {"type": "string", "description": "Exact string to find and replace"},
                            "new_str": {"type": "string", "description": "Replacement string"},
                        },
                        "required": ["path", "old_str", "new_str"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_file",
                    "description": "Delete a file or directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": "List the contents of a directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "default": "."}},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_shell",
                    "description": "Run a shell command in the project directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "timeout": {"type": "integer", "default": 60},
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_codebase",
                    "description": "Search for a pattern in the codebase using ripgrep.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string"},
                            "path": {"type": "string", "default": "."},
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch and read the content of a URL.",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_op",
                    "description": "Run a git subcommand (e.g. subcommand='status', 'diff', 'add -A', etc.).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subcommand": {"type": "string"},
                            "args": {"type": "array", "items": {"type": "string"}, "default": []},
                        },
                        "required": ["subcommand"],
                    },
                },
            },
        ]

    async def dispatch(self, tool_name: str, tool_args: dict[str, Any]) -> ToolResult:
        """Dispatch a tool call by name."""
        dispatch_map = {
            "read_file": lambda a: self.read_file(a["path"]),
            "write_file": lambda a: self.write_file(a["path"], a["content"]),
            "edit_file": lambda a: self.edit_file(a["path"], a["old_str"], a["new_str"]),
            "delete_file": lambda a: self.delete_file(a["path"]),
            "list_dir": lambda a: self.list_dir(a.get("path", ".")),
            "run_shell": lambda a: self.run_shell(a["command"], a.get("timeout", 60)),
            "search_codebase": lambda a: self.search_codebase(a["pattern"], a.get("path", ".")),
            "web_search": lambda a: self.web_search(a["query"]),
            "web_fetch": lambda a: self.web_fetch(a["url"]),
            "git_op": lambda a: self.git_op(a["subcommand"], *a.get("args", [])),
        }
        fn = dispatch_map.get(tool_name)
        if fn is None:
            return {"ok": False, "error": f"Unknown tool: {tool_name}"}
        return await fn(tool_args)
