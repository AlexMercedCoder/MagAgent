"""Task-local AGS capability and checkpoint policy for tool dispatch."""

from __future__ import annotations

import fnmatch
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SideEffectApproval = Callable[[str, dict[str, Any]], Awaitable[bool]]
ToolObserver = Callable[[str, dict[str, Any]], str | None]
ToolDecisionObserver = Callable[[str, bool, str], None]

MUTATING_TOOLS = {
    "write_file",
    "edit_file",
    "delete_file",
    "create_docx",
    "create_pptx",
    "create_svg",
    "create_diagram",
    "create_image",
    "generate_image",
    "db_execute",
    "install_package",
    "git_op",
    "clipboard_write",
}


@dataclass
class GraphToolPolicy:
    allowed_tools: set[str]
    permissions: tuple[str, ...]
    approval: SideEffectApproval | None = None
    approval_prompt: str = "Approve side effects for this graph node?"
    approved: bool = False
    observer: ToolObserver | None = None
    decision_observer: ToolDecisionObserver | None = None


_policy: ContextVar[GraphToolPolicy | None] = ContextVar("magent_graph_tool_policy", default=None)


def set_graph_tool_policy(policy: GraphToolPolicy) -> Token[GraphToolPolicy | None]:
    return _policy.set(policy)


def reset_graph_tool_policy(token: Token[GraphToolPolicy | None]) -> None:
    _policy.reset(token)


async def authorize_graph_tool(tool_name: str, args: dict[str, Any], cwd: str) -> dict[str, Any]:
    policy = _policy.get()
    if policy is None or tool_name == "graph_emit_output":
        return {"ok": True}
    if tool_name not in policy.allowed_tools:
        error = f"RT012 tool {tool_name!r} was not declared by this graph node"
        _observe_decision(policy, tool_name, False, error)
        return {"ok": False, "error": error}
    if policy.observer:
        observer_error = policy.observer(tool_name, args)
        if observer_error:
            _observe_decision(policy, tool_name, False, observer_error)
            return {"ok": False, "error": observer_error}
    permission_error = _permission_error(policy.permissions, tool_name, args, cwd)
    if permission_error:
        error = f"RT012 {permission_error}"
        _observe_decision(policy, tool_name, False, error)
        return {"ok": False, "error": error}
    mutating = tool_name in MUTATING_TOOLS or (
        tool_name == "run_shell" and _shell_may_mutate(str(args.get("command", "")))
    )
    if mutating and policy.approval and not policy.approved:
        if not await policy.approval(policy.approval_prompt, {"tool": tool_name, "args": args}):
            error = "RT015 side-effect checkpoint rejected"
            _observe_decision(policy, tool_name, False, error)
            return {"ok": False, "error": error}
        policy.approved = True
    _observe_decision(policy, tool_name, True, "")
    return {"ok": True}


def _observe_decision(policy: GraphToolPolicy, tool_name: str, allowed: bool, error: str) -> None:
    if policy.decision_observer:
        policy.decision_observer(tool_name, allowed, error)


def _permission_error(
    permissions: tuple[str, ...], tool_name: str, args: dict[str, Any], cwd: str
) -> str:
    if not permissions:
        return "node declares no permissions"
    if tool_name in {
        "read_file",
        "read_file_range",
        "outline_file",
        "list_dir",
        "search_codebase",
        "read_image",
        "diff_files",
    }:
        return (
            ""
            if _path_allowed(
                permissions, "fs:read:", str(args.get("path", args.get("path_a", "."))), cwd
            )
            else "filesystem read exceeds the requested permission ceiling"
        )
    if tool_name in MUTATING_TOOLS and any(key in args for key in ("path", "file_path")):
        raw = str(args.get("path", args.get("file_path", "")))
        return (
            ""
            if _path_allowed(permissions, "fs:write:", raw, cwd)
            else "filesystem write exceeds the requested permission ceiling"
        )
    if tool_name == "run_shell":
        command = str(args.get("command", ""))
        patterns = [
            item.removeprefix("shell:exec:")
            for item in permissions
            if item.startswith("shell:exec:")
        ]
        return (
            ""
            if any(fnmatch.fnmatch(command, pattern) for pattern in patterns)
            else "shell command exceeds the requested permission ceiling"
        )
    if tool_name.startswith(("web_", "http_", "browser_")):
        return (
            ""
            if any(item.startswith(("net:", "web:")) for item in permissions)
            else "network access exceeds the requested permission ceiling"
        )
    return ""


def _path_allowed(permissions: tuple[str, ...], prefix: str, raw: str, cwd: str) -> bool:
    root = Path(cwd).resolve()
    path = (
        (root / raw).resolve(strict=False)
        if not Path(raw).is_absolute()
        else Path(raw).resolve(strict=False)
    )
    if path != root and root not in path.parents:
        return False
    relative = str(path.relative_to(root)) if path != root else "."
    patterns = [item.removeprefix(prefix) for item in permissions if item.startswith(prefix)]
    return any(pattern in {"**", "*"} or fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def _shell_may_mutate(command: str) -> bool:
    lowered = f" {command.lower()} "
    return any(
        token in lowered
        for token in (
            " >",
            " >>",
            " rm ",
            " mv ",
            " cp ",
            " install ",
            " commit ",
            " push ",
            " apply ",
        )
    )
