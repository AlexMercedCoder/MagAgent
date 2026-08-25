"""Built-in tool registry and executor for MagAgent.

Tools are organized into tiers:
  SILENT (0) - read-only, always auto-approved
  AUTO   (1) - shown, auto-approved in balanced/silent mode
  CONFIRM(2) - requires inline y/n prompt in balanced mode
  BLOCK  (3) - always requires explicit typed confirmation
"""

from __future__ import annotations

import asyncio
import json
import shutil as shutil
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from rich.console import Console

from magent.permissions import (
    PermissionResult,
    RiskTier,
    check_permission,
    classify_file_op,
)
from magent.tool_packs import filter_tool_definitions_for_user
from magent.tools.artifacts import ArtifactToolsMixin
from magent.tools.data import DataToolsMixin
from magent.tools.files import FileToolsMixin
from magent.tools.messaging import MessagingToolsMixin
from magent.tools.registry import strip_tool_activity, validate_tool_args
from magent.tools.shell import ShellToolsMixin
from magent.tools.system import SystemToolsMixin
from magent.tools.types import DEFAULT_TOOL_BUDGETS, OPAQUE_RESULT_KEYS, ToolResult
from magent.tools.web import WebToolsMixin

console = Console()


def _running_tool_status(tool_name: str, args: dict[str, Any], elapsed: float) -> str:
    label = tool_name
    if tool_name == "run_shell":
        command = str(args.get("command") or "").strip()
        if command:
            label = command[:90]
    return f"Still running {label}... {int(elapsed)}s elapsed"


def _normalize_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Normalize common provider/model argument aliases before dispatch."""
    normalized = dict(args)
    path_alias_tools = {
        "read_file",
        "read_file_range",
        "outline_file",
        "write_file",
        "create_docx",
        "create_pptx",
        "create_svg",
        "create_diagram",
        "create_image",
        "generate_image",
        "edit_file",
        "delete_file",
        "list_dir",
        "open_file",
        "read_image",
        "browser_screenshot",
    }
    if tool_name in path_alias_tools and "path" not in normalized:
        for alias in ("file_path", "filepath", "filename", "file", "target_path", "output_file"):
            if alias in normalized:
                normalized["path"] = normalized[alias]
                break
    if tool_name == "write_file" and "content" not in normalized:
        for alias in (
            "contents",
            "file_content",
            "file_contents",
            "full_content",
            "html",
            "markdown",
            "text",
            "body",
            "data",
            "source",
        ):
            if alias in normalized:
                normalized["content"] = normalized[alias]
                break
    if tool_name == "edit_file":
        if "old_str" not in normalized and "old_string" in normalized:
            normalized["old_str"] = normalized["old_string"]
        if "new_str" not in normalized and "new_string" in normalized:
            normalized["new_str"] = normalized["new_string"]
    return normalized


class ToolExecutor(
    DataToolsMixin,
    SystemToolsMixin,
    MessagingToolsMixin,
    FileToolsMixin,
    WebToolsMixin,
    ShellToolsMixin,
    ArtifactToolsMixin,
):
    """Executes agent tools with integrated permission checking."""

    def __init__(
        self,
        cwd: str,
        permission_mode: str = "balanced",
        allowed_shell_patterns: list[str] | None = None,
        trusted_shell_patterns: list[str] | None = None,
        show_tool_calls: bool = True,
        username: str = "default",
        tool_budgets: dict[str, int] | None = None,
        session_id: str = "manual",
        interactive_permissions: bool = True,
        permission_prompt: Any = None,
        shell_sandbox: str = "off",
        shell_sandbox_network: bool = False,
        config: Any | None = None,
        activity_callback: Callable[[str, dict[str, Any], float, str], None] | None = None,
        allowed_tools: set[str] | frozenset[str] | None = None,
    ):
        self.cwd = cwd
        self.permission_mode = permission_mode
        self.allowed_shell_patterns = allowed_shell_patterns or []
        self.trusted_shell_patterns = trusted_shell_patterns or []
        self.session_shell_patterns: list[str] = []
        self.show_tool_calls = show_tool_calls
        self.username = username
        self.tool_budgets = {**DEFAULT_TOOL_BUDGETS, **(tool_budgets or {})}
        self.session_id = session_id
        self.interactive_permissions = interactive_permissions
        # A front end with a user but no console supplies this; without one a
        # non-interactive caller can only refuse.
        self.permission_prompt = permission_prompt
        # Optional isolation for run_shell, independent of the permission tier.
        self.shell_sandbox = str(shell_sandbox or "off")
        self.shell_sandbox_network = bool(shell_sandbox_network)
        self.config = config
        self.activity_callback = activity_callback
        self.allowed_tools = frozenset(allowed_tools) if allowed_tools is not None else None
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._active_processes: set[asyncio.subprocess.Process] = set()
        # Audit trail of file access outside the project root.
        self._out_of_project_access: list[dict[str, Any]] = []

    async def cancel_active(self) -> None:
        """Cancel active tool work and terminate subprocesses owned by this executor."""
        tasks = list(self._active_tasks)
        for task in tasks:
            task.cancel()
        for proc in list(self._active_processes):
            with suppress(ProcessLookupError):
                if proc.returncode is None:
                    proc.kill()
            with suppress(Exception):
                await proc.wait()
        if tasks:
            with suppress(Exception):
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        self._active_processes.clear()
        self._active_tasks.clear()

    def has_active_work(self) -> bool:
        return bool(self._active_tasks or self._active_processes)

    def _checkpoint(self, abs_path: Path, operation: str) -> str:
        try:
            from magent.workbench import create_checkpoint

            item = create_checkpoint(self.username, self.cwd, abs_path, operation, self.session_id)
            return str(item.get("id", ""))
        except Exception:
            return ""

    def _resolve_path(self, path: str) -> Path:
        root = Path(self.cwd).resolve()
        raw = Path(path).expanduser()
        return (raw if raw.is_absolute() else root / raw).resolve(strict=False)

    def _path_tier(self, op: str, path: str) -> tuple[Path, RiskTier]:
        resolved = self._resolve_path(path)
        tier = classify_file_op(op, path, self.cwd)
        self._audit_out_of_project(op, resolved, tier)
        return resolved, tier

    def _audit_out_of_project(self, op: str, resolved: Path, tier: RiskTier) -> None:
        """Record access outside the project even when it is auto-approved.

        In `silent` mode tiers 0-2 auto-resolve, so reads, writes and deletes
        anywhere on disk happened with no prompt *and* no audit line —
        containment was only ever a tier, never a record.
        """
        root = Path(self.cwd).resolve()
        if resolved == root or root in resolved.parents:
            return
        self._out_of_project_access.append({"op": op, "path": str(resolved), "tier": int(tier)})
        if self.show_tool_calls:
            console.print(f"  [yellow]⚠ {op} outside project:[/yellow] [dim]{resolved}[/dim]")

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        if self.show_tool_calls and tier > RiskTier.SILENT:
            from magent.permissions import TIER_LABELS

            tier_label = TIER_LABELS.get(tier, str(tier))
            console.print(
                f"  [dim]🔧 {name}[/dim] [dim cyan][{tier_label}][/dim cyan] [dim]{desc[:80]}[/dim]"
            )

    def _check_permission(self, action_description: str, tier: RiskTier) -> PermissionResult:
        return check_permission(
            action_description,
            tier,
            self.permission_mode,
            interactive=self.interactive_permissions,
            ask=self.permission_prompt,
        )

    def _permission_denied(self, perm: PermissionResult) -> ToolResult:
        error = (
            "Permission required"
            if perm.reason == "permission-required"
            else "Permission denied by user"
        )
        return {
            "ok": False,
            "error": error,
            "permission_required": perm.reason == "permission-required",
            "permission_tier": int(perm.tier),
            "permission_reason": perm.reason,
        }

    async def _graph_emit_output(self, name: str, value: Any) -> ToolResult:
        from magent.agraph.output import emit_output

        return emit_output(name, value)

    # ─────────────────────────────────────────────
    # TOOL DEFINITIONS (OpenAI function-calling format)
    # ─────────────────────────────────────────────

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        from magent.tools.catalog import built_in_tool_definitions
        from magent.tools.registry import reconcile_required_with_signatures

        definitions = reconcile_required_with_signatures(
            filter_tool_definitions_for_user(built_in_tool_definitions(), self.username),
            self,
        )
        if self.allowed_tools is None:
            return definitions
        return [
            item for item in definitions
            if item.get("function", {}).get("name") in self.allowed_tools
        ]

    def get_tool_definitions_for_message(self, message: str) -> list[dict[str, Any]]:
        from magent.tools.catalog import select_tool_definitions_for_message

        return select_tool_definitions_for_message(self.get_tool_definitions(), message)

    async def dispatch(self, tool_name: str, tool_args: dict[str, Any]) -> ToolResult:
        """Dispatch a tool call by name."""
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            return {"ok": False, "error": f"Tool disabled by active agent profile: {tool_name}"}
        a = _normalize_tool_args(tool_name, strip_tool_activity(tool_args))
        from magent.agraph.runtime_context import authorize_graph_tool

        graph_authorization = await authorize_graph_tool(tool_name, a, self.cwd)
        if not graph_authorization.get("ok"):
            return graph_authorization
        raw = bool(a.pop("raw", False))
        definition = next(
            (
                item
                for item in self.get_tool_definitions()
                if item.get("function", {}).get("name") == tool_name
            ),
            None,
        )
        if definition:
            validation = validate_tool_args(definition, a)
            if not validation["ok"]:
                return {
                    "ok": False,
                    "error": f"Missing required arguments for {tool_name}: {', '.join(validation['missing'])}",
                    "missing": validation["missing"],
                }
        dispatch_map: dict[str, Any] = {
            "graph_emit_output": lambda: self._graph_emit_output(a["name"], a["value"]),
            "read_file": lambda: self.read_file(a["path"]),
            "read_file_range": lambda: self.read_file_range(
                a["path"], a.get("start_line", 1), a.get("end_line")
            ),
            "outline_file": lambda: self.outline_file(a["path"], a.get("max_symbols", 200)),
            "write_file": lambda: self.write_file(a["path"], a["content"]),
            "create_docx": lambda: self.create_docx(
                a["path"], a["title"], a["sections"], a.get("subtitle", "")
            ),
            "create_pptx": lambda: self.create_pptx(
                a["path"], a["title"], a["slides"], a.get("subtitle", "")
            ),
            "create_svg": lambda: self.create_svg(
                a["path"],
                a["elements"],
                a.get("title", ""),
                a.get("width", 1200),
                a.get("height", 800),
            ),
            "create_diagram": lambda: self.create_diagram(
                a["path"],
                a["title"],
                a["nodes"],
                a.get("edges", []),
                a.get("direction", "TD"),
            ),
            "create_image": lambda: self.create_image(
                a["path"],
                a["elements"],
                a.get("title", ""),
                a.get("width", 1200),
                a.get("height", 800),
                a.get("background", "#ffffff"),
            ),
            "generate_image": lambda: self.generate_image(
                a["path"],
                a["prompt"],
                a.get("aspect_ratio", "landscape"),
                a.get("reference_image", ""),
            ),
            "edit_file": lambda: self.edit_file(a["path"], a["old_str"], a["new_str"]),
            "delete_file": lambda: self.delete_file(a["path"]),
            "list_dir": lambda: self.list_dir(a.get("path", ".")),
            "diff_files": lambda: self.diff_files(a["path_a"], a["path_b"]),
            "compress": lambda: self.compress(
                a["source_path"], a["output_path"], a.get("format", "zip")
            ),
            "extract": lambda: self.extract(a["archive_path"], a.get("output_dir", ".")),
            "run_shell": lambda: self.run_shell(a["command"], a.get("timeout", 60)),
            "run_python": lambda: self.run_python(a["code"], a.get("timeout", 30)),
            "install_package": lambda: self.install_package(a["package"], a.get("version", "")),
            "search_codebase": lambda: self.search_codebase(a["pattern"], a.get("path", ".")),
            "web_search": lambda: self.web_search(a["query"], a.get("max_results", 8)),
            "web_fetch": lambda: self.web_fetch(a["url"], a.get("extract_article", True)),
            "deep_research": lambda: self.deep_research(
                a["topic"],
                a.get("questions"),
                a.get("max_sources", 6),
                a.get("fetch_sources", True),
            ),
            "http_request": lambda: self.http_request(
                a["method"], a["url"], a.get("headers"), a.get("body"), a.get("timeout", 30)
            ),
            "browser_snapshot": lambda: self.browser_snapshot(a["url"], a.get("wait_ms", 500)),
            "browser_screenshot": lambda: self.browser_screenshot(
                a["url"], a["path"], a.get("wait_ms", 500)
            ),
            "json_query": lambda: self.json_query(a["path_or_json"], a["query"]),
            "system_info": lambda: self.system_info(),
            "notify": lambda: self.notify(a["title"], a["message"], a.get("urgency", "normal")),
            "clipboard_read": lambda: self.clipboard_read(),
            "clipboard_write": lambda: self.clipboard_write(a["text"]),
            "open_file": lambda: self.open_file(a["path"]),
            "read_image": lambda: self.read_image(a["path"]),
            "db_query": lambda: self.db_query(
                a["sql"], a.get("params"), a.get("db_name", "default")
            ),
            "db_execute": lambda: self.db_execute(
                a["sql"], a.get("params"), a.get("db_name", "default")
            ),
            "db_list_tables": lambda: self.db_list_tables(a.get("db_name", "default")),
            "db_schema": lambda: self.db_schema(a["table"], a.get("db_name", "default")),
            "db_list_databases": lambda: self.db_list_databases(),
            "git_op": lambda: self.git_op(a["subcommand"], *a.get("args", [])),
            "magent_docs_search": lambda: self.magent_docs_search(a["query"], a.get("limit", 5)),
            "list_sessions": lambda: self.list_sessions(),
            "send_session_message": lambda: self.send_session_message(
                a["target"], a["message"], a.get("task_id", "")
            ),
        }
        fn = dispatch_map.get(tool_name)
        if fn is None:
            return {"ok": False, "error": f"Unknown tool: {tool_name}"}
        try:
            task = asyncio.create_task(fn())
            self._active_tasks.add(task)
            started = asyncio.get_running_loop().time()
            wait_seconds = 6.0
            while True:
                done, _pending = await asyncio.wait({task}, timeout=wait_seconds)
                if done:
                    result = task.result()
                    break
                if self.show_tool_calls:
                    elapsed = asyncio.get_running_loop().time() - started
                    status = _running_tool_status(tool_name, a, elapsed)
                    console.print(f"[dim]{status}[/dim]")
                    if self.activity_callback:
                        self.activity_callback(tool_name, a, elapsed, status)
                wait_seconds = 30.0
        except KeyError as e:
            missing = str(e).strip("'")
            return {
                "ok": False,
                "error": f"Missing required argument '{missing}' for tool {tool_name}",
                "tool": tool_name,
                "args": a,
            }
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            if "task" in locals():
                self._active_tasks.discard(task)
        return result if raw else self._budget_result(tool_name, result)

    def _budget_result(self, tool_name: str, result: ToolResult) -> ToolResult:
        budget = int(self.tool_budgets.get(tool_name, self.tool_budgets.get("default", 8000)))
        if budget <= 0:
            return result
        changed = False
        output = dict(result)
        for key, value in list(output.items()):
            if key in OPAQUE_RESULT_KEYS:
                # Base64 image payloads are not prose: appending a truncation
                # marker produced undecodable data that was handed straight to
                # vision models. Drop the field instead of corrupting it.
                if isinstance(value, str) and len(value) > budget:
                    output.pop(key)
                    output[f"{key}_omitted"] = (
                        f"{len(value)} characters of binary payload omitted; pass raw=true to receive it"
                    )
                    changed = True
                continue
            if isinstance(value, str) and len(value) > budget:
                output[key] = value[:budget].rstrip() + (
                    f"\n\n[...{key} truncated at {budget} chars; pass raw=true for full output...]"
                )
                changed = True
            elif isinstance(value, list) and len(json.dumps(value, default=str)) > budget:
                kept = []
                size = 2
                for item in value:
                    item_size = len(json.dumps(item, default=str))
                    if size + item_size > budget:
                        break
                    kept.append(item)
                    size += item_size
                output[key] = kept
                output[f"{key}_truncated"] = True
                changed = True
        if changed:
            output["budgeted"] = True
            output["budget_chars"] = budget
        return output
