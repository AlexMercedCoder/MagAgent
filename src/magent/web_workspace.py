"""Bounded, project-confined workspace services for the local Web UI."""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_INLINE_BYTES = 256 * 1024
MAX_CONTEXT_BYTES = 750 * 1024
MAX_CONTEXT_FILES = 20
MAX_OUTPUT_BYTES = 256 * 1024
IGNORED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
}
TEXT_SUFFIXES = {
    ".c",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
ARTIFACT_SUFFIXES = {
    ".csv",
    ".docx",
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".svg",
    ".txt",
    ".webp",
    ".xlsx",
}
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class WorkspaceError(ValueError):
    """A workspace request that cannot safely be fulfilled."""


class WorkspaceService:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, raw: str, *, allow_internal_attachment: bool = True) -> Path:
        if not raw or "\x00" in raw:
            raise WorkspaceError("path is required")
        candidate = (self.root / raw).resolve(strict=False)
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            raise WorkspaceError("path escapes the selected workspace") from None
        if relative.parts and relative.parts[0] == ".magent":
            allowed = len(relative.parts) > 1 and relative.parts[1] == "attachments"
            if not (allow_internal_attachment and allowed):
                raise WorkspaceError("MagAgent's internal state is not exposed in the workspace UI")
        return candidate

    def list_files(self, query: str = "", limit: int = 500) -> dict[str, Any]:
        needle = query.strip().lower()
        files: list[dict[str, Any]] = []
        capped = max(1, min(int(limit), 1000))
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            if (
                relative.parts
                and relative.parts[0] == ".magent"
                and (len(relative.parts) < 2 or relative.parts[1] != "attachments")
            ):
                continue
            if not path.is_file() or (needle and needle not in relative.as_posix().lower()):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            files.append(
                {
                    "path": relative.as_posix(),
                    "name": path.name,
                    "size": size,
                    "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    "artifact": path.suffix.lower() in ARTIFACT_SUFFIXES,
                }
            )
            if len(files) >= capped:
                break
        return {"ok": True, "files": files, "truncated": len(files) >= capped}

    def preview(self, raw: str) -> dict[str, Any]:
        path = self._path(raw)
        if not path.is_file():
            raise WorkspaceError("file not found")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise WorkspaceError(f"file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        is_text = path.suffix.lower() in TEXT_SUFFIXES or mime.startswith("text/")
        result: dict[str, Any] = {
            "ok": True,
            "path": path.relative_to(self.root).as_posix(),
            "name": path.name,
            "size": size,
            "mime": mime,
            "text": is_text,
        }
        if is_text:
            result["content"] = data.decode("utf-8", errors="replace")
        else:
            result["data_url"] = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        return result

    def upload(self, name: str, encoded: str, conversation_id: str = "shared") -> dict[str, Any]:
        safe_name = Path(name).name
        if not safe_name or safe_name in {".", ".."}:
            raise WorkspaceError("upload filename is invalid")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise WorkspaceError("upload data is not valid base64") from None
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError(f"uploads are limited to {MAX_FILE_BYTES // (1024 * 1024)} MB")
        safe_conversation = re.sub(r"[^A-Za-z0-9_.-]", "_", conversation_id)[:80] or "shared"
        target = self.root / ".magent" / "attachments" / safe_conversation / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {
            "ok": True,
            "file": {
                "path": target.relative_to(self.root).as_posix(),
                "name": safe_name,
                "size": len(data),
            },
        }

    def context_prompt(self, paths: Any) -> tuple[str, list[dict[str, Any]]]:
        if not isinstance(paths, list):
            raise WorkspaceError("context paths must be a list")
        if len(paths) > MAX_CONTEXT_FILES:
            raise WorkspaceError(f"select no more than {MAX_CONTEXT_FILES} context files")
        blocks: list[str] = []
        refs: list[dict[str, Any]] = []
        inline_total = 0
        for item in paths:
            raw = str(item)
            path = self._path(raw)
            if not path.is_file():
                raise WorkspaceError(f"context file not found: {raw}")
            relative = path.relative_to(self.root).as_posix()
            size = path.stat().st_size
            inline = path.suffix.lower() in TEXT_SUFFIXES and size <= MAX_INLINE_BYTES
            if inline and inline_total + size <= MAX_CONTEXT_BYTES:
                content = path.read_text(encoding="utf-8", errors="replace")
                blocks.append(f"### {relative}\n```\n{content}\n```")
                inline_total += size
            else:
                blocks.append(f"- `{relative}` (workspace file; inspect with tools if needed)")
            refs.append({"path": relative, "size": size, "inline": inline})
        if not blocks:
            return "", refs
        return "\n\n# User-selected workspace context\n\n" + "\n\n".join(blocks), refs

    def git(self) -> dict[str, Any]:
        status = self._git(["status", "--short", "--branch"], check=False)
        if not status["ok"] and "not a git repository" in str(status.get("error", "")).lower():
            return {
                "ok": True,
                "is_repository": False,
                "status": [],
                "branches": [],
                "worktrees": [],
                "notice": "This project folder is not a Git repository. Git actions are unavailable until you initialize one.",
                "error": "",
            }
        worktrees = self._git(["worktree", "list", "--porcelain"], check=False)
        branches = self._git(["branch", "--format=%(refname:short)"], check=False)
        parsed_worktrees = self._parse_worktrees(worktrees.get("stdout", ""))
        for item in parsed_worktrees:
            item["current"] = str(Path(item.get("worktree", "")).resolve() == self.root).lower()
        return {
            "ok": status["ok"],
            "is_repository": True,
            "status": status.get("stdout", "").splitlines(),
            "branches": branches.get("stdout", "").splitlines(),
            "worktrees": parsed_worktrees,
            "error": status.get("error", ""),
        }

    def diff(self, staged: bool = False) -> dict[str, Any]:
        result = self._git(["diff", "--cached"] if staged else ["diff"], check=False)
        return {
            "ok": result["ok"],
            "diff": result.get("stdout", "")[:MAX_OUTPUT_BYTES],
            "error": result.get("error", ""),
        }

    def git_action(self, action: str, raw: str) -> dict[str, Any]:
        path = self._path(raw, allow_internal_attachment=False)
        relative = path.relative_to(self.root).as_posix()
        commands = {
            "stage": ["add", "--", relative],
            "unstage": ["restore", "--staged", "--", relative],
            "discard": ["restore", "--worktree", "--", relative],
        }
        if action not in commands:
            raise WorkspaceError("unsupported git action")
        return self._git(commands[action])

    def create_worktree(
        self, branch: str, directory: str, create_branch: bool = False
    ) -> dict[str, Any]:
        if not SAFE_BRANCH.fullmatch(branch) or ".." in branch.split("/"):
            raise WorkspaceError("branch name is invalid")
        target = self._worktree_path(directory)
        if target == self.root:
            raise WorkspaceError("worktree directory must not be the current workspace")
        args = ["worktree", "add"]
        if create_branch:
            args += ["-b", branch, str(target)]
        else:
            args += [str(target), branch]
        return self._git(args, timeout=120)

    def remove_worktree(self, directory: str) -> dict[str, Any]:
        target = self._worktree_path(directory)
        if target == self.root:
            raise WorkspaceError("cannot remove the current workspace")
        return self._git(["worktree", "remove", str(target)], timeout=120)

    def _worktree_path(self, raw: str) -> Path:
        if not raw or "\x00" in raw:
            raise WorkspaceError("worktree directory is required")
        target = (self.root / raw).resolve(strict=False)
        parent = self.root.parent.resolve()
        try:
            target.relative_to(parent)
        except ValueError:
            raise WorkspaceError(
                "worktrees must stay beside or inside the selected workspace"
            ) from None
        if target == self.root or target == parent:
            raise WorkspaceError(
                "worktree directory must not be the current workspace or its parent"
            )
        return target

    def terminal(self, command: str) -> dict[str, Any]:
        if not command.strip() or len(command) > 4000:
            raise WorkspaceError("command must contain 1 to 4000 characters")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc
        if not argv:
            raise WorkspaceError("command is empty")
        try:
            completed = subprocess.run(
                argv,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                env={**os.environ, "PAGER": "cat", "GIT_PAGER": "cat"},
            )
            stdout = completed.stdout[-MAX_OUTPUT_BYTES:]
            stderr = completed.stderr[-MAX_OUTPUT_BYTES:]
            return {
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "returncode": 127,
                "stdout": "",
                "stderr": f"command not found: {argv[0]}",
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "returncode": 124,
                "stdout": str(exc.stdout or "")[-MAX_OUTPUT_BYTES:],
                "stderr": "command timed out after 60 seconds",
            }

    def _git(self, args: list[str], *, check: bool = True, timeout: int = 30) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": str(exc), "stdout": "", "stderr": str(exc)}
        result = {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-MAX_OUTPUT_BYTES:],
            "stderr": completed.stderr[-MAX_OUTPUT_BYTES:],
        }
        if check and completed.returncode:
            raise WorkspaceError(completed.stderr.strip() or "git command failed")
        if completed.returncode:
            result["error"] = completed.stderr.strip() or "git command failed"
        return result

    @staticmethod
    def _parse_worktrees(text: str) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in [*text.splitlines(), ""]:
            if not line:
                if current:
                    records.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value
        return records


def extension_inventory(username: str | None, project: str | Path) -> dict[str, Any]:
    from magent.plugins import list_plugins
    from magent.skills import SkillRegistry
    from magent.tool_gateway import gateway_status
    from magent.web_extensions import public_mcp_config

    registry = SkillRegistry(extra_dirs=[Path(project) / ".magent" / "skills"])
    registry.load(respect_lockfile=False)
    mcp: list[dict[str, Any]] = []
    capabilities: list[dict[str, Any]] = []
    if username:
        from magent.config import load_config

        config = load_config(username)
        for name, value in sorted(config.mcp_servers.get("servers", {}).items()):
            public = public_mcp_config(value) if isinstance(value, dict) else {}
            mcp.append(
                {
                    "name": name,
                    **public,
                }
            )
        capabilities = gateway_status(config).get("backends", [])
    plugins = [
        {
            "name": str(item.get("name") or ""),
            "version": str(item.get("version") or ""),
            "enabled": bool(item.get("enabled")),
            "integrity": str(item.get("integrity") or "unrecorded"),
            "valid": bool(item.get("valid")),
        }
        for item in list_plugins().get("plugins", [])
    ]
    return {
        "ok": True,
        "plugins": plugins,
        "skills": [
            {
                **item,
                "editable": str(item.get("path") or "").startswith(
                    str((Path(project).resolve() / ".magent" / "skills").resolve())
                ),
                "body": (
                    Path(str(item.get("path"))).read_text(encoding="utf-8")[:20000]
                    if str(item.get("path") or "").startswith(
                        str((Path(project).resolve() / ".magent" / "skills").resolve())
                    )
                    else ""
                ),
            }
            for item in registry.list_all()
        ],
        "mcp_servers": mcp,
        "capabilities": capabilities,
    }
