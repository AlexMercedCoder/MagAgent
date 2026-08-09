"""Shell, Python, package-install, and subprocess-backed search tools."""

from __future__ import annotations

import asyncio
import fnmatch
import importlib.util
import re
import shlex
import shutil
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from magent.permissions import PermissionResult, RiskTier, classify_shell_command
from magent.sandbox import execute_plan_sandbox, sandbox_plan_preview
from magent.tools.types import ToolResult

console = Console()


def _uses_shell_syntax(command: str) -> bool:
    """Return true when a command needs shell parsing beyond argv splitting."""
    return bool(re.search(r"(\|\||&&|[;\n|<>]|\$\(|\{[^{}\s]+,[^{}]+})", command))


def _first_command_name(command: str) -> str:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        for token in lexer:
            if token not in {"|", "||", "&&", ";", ">", ">>", "<"}:
                return Path(token).name.lower()
    except ValueError:
        return ""
    return ""


def _looks_like_read_only_fetch_pipeline(command: str) -> bool:
    """Return true for fetch-and-inspect pipelines worth broader approval."""
    if not re.search(r"\b(curl|wget)\b", command) or "|" not in command:
        return False
    if re.search(r"(?<![<>&])>>?(?![>&])", command) or "<<" in command:
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    write_flags = {
        "-d",
        "--data",
        "--data-raw",
        "--data-binary",
        "--data-urlencode",
        "-F",
        "--form",
        "--form-string",
        "-T",
        "--upload-file",
        "-o",
        "--output",
        "-O",
        "--remote-name",
        "--remote-header-name",
        "-X",
        "--request",
    }
    if any(token in write_flags for token in tokens):
        return False
    allowed_heads = {
        "curl",
        "wget",
        "grep",
        "head",
        "tail",
        "sed",
        "awk",
        "cut",
        "tr",
        "od",
        "wc",
        "sort",
        "cat",
    }
    expect_head = True
    for token in tokens:
        if token in {"|", "||", "&&", ";"}:
            expect_head = True
            continue
        if token in {"2>&1", "1>&2"}:
            continue
        if token in {">", ">>", "<", "2>", "2>>"}:
            return False
        if expect_head:
            if Path(token).name.lower() not in allowed_heads:
                return False
            expect_head = False
    return True


def _effective_shell_timeout(command: str, requested_timeout: int) -> int:
    """Give known package-install commands enough time unless caller overrides."""
    if requested_timeout != 60:
        return requested_timeout
    lowered = f" {command.lower()} "
    package_install_markers = (
        " npm install",
        " npm ci",
        " yarn install",
        " pnpm install",
        " bun install",
    )
    if any(marker in lowered for marker in package_install_markers):
        return 300
    return requested_timeout


async def _create_shell_process(command: str, cwd: str | Path) -> asyncio.subprocess.Process:
    """Run shell syntax through bash when available so brace expansion behaves."""
    bash = shutil.which("bash")
    if bash:
        return await asyncio.create_subprocess_exec(
            bash,
            "-lc",
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    return await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _create_exec_process(*argv: str, cwd: str | Path) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _prefer_platform_python_command(command: str, *, platform: str | None = None) -> str:
    """On macOS, prefer the Python 3 command family over ambiguous python/pip."""
    if (platform or sys.platform) != "darwin":
        return command
    rewritten = re.sub(r"(^|[;&|\n]\s*)pip(?=\s)", r"\1python3 -m pip", command)
    return re.sub(r"(^|[;&|\n]\s*)python(?=\s)", r"\1python3", rewritten)


def _shell_native_file_tool_guidance(command: str) -> str:
    """Return guidance when shell is used for work native file tools should do."""
    scrubbed = re.sub(r"\b[12]?>&[12]\b", "", command)
    scrubbed = re.sub(r"\b[12]?>\s*/dev/null\b", "", scrubbed)
    if "<<" in scrubbed or re.search(r"(?<![<>&])>>?(?![>&])", scrubbed):
        return "Shell redirection/heredocs are not used for file writes. Use write_file or edit_file instead."

    try:
        argv = shlex.split(command)
    except ValueError:
        argv = []
    head = Path(argv[0]).name.lower() if argv else ""
    if head in {"tee", "touch"}:
        return f"`{head}` writes files. Use write_file or edit_file instead."

    lower = command.lower()
    if head in {"python", "python3"} and (
        "open(" in lower
        or ".write_text(" in lower
        or ".write_bytes(" in lower
        or "path(" in lower
    ):
        return "Python shell snippets that write files are disabled. Use write_file or edit_file instead."
    return ""


class ShellToolsMixin:
    """Shell/process capability implementation mixed into the tool executor."""

    cwd: str
    permission_mode: str
    allowed_shell_patterns: list[str]
    trusted_shell_patterns: list[str]
    session_shell_patterns: list[str]
    show_tool_calls: bool
    username: str
    interactive_permissions: bool
    _active_processes: set[asyncio.subprocess.Process]

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        raise NotImplementedError

    def _check_permission(self, action_description: str, tier: RiskTier) -> PermissionResult:
        raise NotImplementedError

    def _permission_denied(self, perm: PermissionResult) -> ToolResult:
        raise NotImplementedError

    def _path_tier(self, op: str, path: str) -> tuple[Path, RiskTier]:
        raise NotImplementedError

    def _trusted_shell_match(self, command: str) -> bool:
        patterns = [*self.trusted_shell_patterns, *self.session_shell_patterns]
        return any(fnmatch.fnmatch(command.strip(), pattern) for pattern in patterns)

    def _remember_trusted_shell_pattern(self, command: str) -> None:
        try:
            from magent.config import load_user_profile, save_user_profile

            profile = load_user_profile(self.username)
            permissions = profile.setdefault("permissions", {})
            patterns = list(permissions.get("trusted_shell_patterns") or [])
            if command not in patterns:
                patterns.append(command)
            permissions["trusted_shell_patterns"] = patterns
            save_user_profile(self.username, profile)
            self.trusted_shell_patterns = patterns
        except Exception:
            self.session_shell_patterns.append(command)

    def _shell_trust_pattern(self, command: str, tier: RiskTier) -> str:
        if _looks_like_read_only_fetch_pipeline(command):
            head = _first_command_name(command)
            return f"{head} * | *" if head in {"curl", "wget"} else command
        if tier >= RiskTier.CONFIRM:
            return command
        if not re.search(r"(\|\||&&|[;\n|<>]|\$\()", command):
            return command
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            return command
        pieces: list[str] = []
        expect_head = True
        for token in tokens:
            if token in {"|", "||", "&&", ";"}:
                pieces.append(token)
                expect_head = True
                continue
            if token in {">", ">>", "<", "2>", "2>>", "2>&1", "1>&2"}:
                pieces.append(token)
                expect_head = False
                continue
            if expect_head:
                pieces.append(f"{Path(token).name} *")
                expect_head = False
        return " ".join(pieces) if pieces else command

    def _check_shell_permission(self, command: str, tier: RiskTier) -> PermissionResult:
        if self._trusted_shell_match(command):
            return PermissionResult(True, RiskTier.AUTO, "trusted-shell")
        if not self.interactive_permissions or self.permission_mode == "yolo":
            return self._check_permission(f"Run: `{command}`", tier)
        if tier < RiskTier.CONFIRM:
            return PermissionResult(True, tier, "auto")
        title = (
            "[red]\u26a0 Permission Required[/red]"
            if tier == RiskTier.BLOCK
            else "[yellow]Permission[/yellow]"
        )
        border = "red" if tier == RiskTier.BLOCK else "yellow"
        console.print(
            Panel(
                f"[bold]{'High risk shell action' if tier == RiskTier.BLOCK else 'Shell action requires confirmation'}[/bold]\n\n"
                f"Run: `{command}`\n\n"
                "[dim]Choose whether this approval should last once, for this session, or be saved for future sessions.[/dim]",
                title=title,
                border_style=border,
            )
        )
        choice = Prompt.ask(
            "Approve",
            choices=["once", "session", "always", "no", "o", "s", "a", "n"],
            default="once" if tier == RiskTier.CONFIRM else "no",
        ).lower()
        if choice in {"no", "n"}:
            return PermissionResult(False, tier, "user-denied")
        if choice in {"session", "s"}:
            pattern = self._shell_trust_pattern(command, tier)
            if pattern not in self.session_shell_patterns:
                self.session_shell_patterns.append(pattern)
            console.print(f"[dim]Approved for this session; running `{command}`.[/dim]")
            return PermissionResult(True, tier, "user-session-allow")
        if choice in {"always", "a"}:
            pattern = self._shell_trust_pattern(command, tier)
            self._remember_trusted_shell_pattern(pattern)
            console.print(f"[dim]Saved approval for `{pattern}`; running `{command}`.[/dim]")
            return PermissionResult(True, tier, "user-persistent-allow")
        console.print(f"[dim]Approved once; running `{command}`.[/dim]")
        return PermissionResult(True, tier, "user-confirmed")

    async def run_shell(self, command: str, timeout: int = 60) -> ToolResult:
        original_command = command
        command = _prefer_platform_python_command(command)
        timeout = _effective_shell_timeout(command, timeout)
        if command != original_command and self.show_tool_calls:
            console.print(f"[dim]Using macOS Python command: `{command}`[/dim]")
        native_guidance = _shell_native_file_tool_guidance(command)
        if native_guidance:
            self._log_tool("run_shell", command, RiskTier.BLOCK)
            return {
                "ok": False,
                "error": native_guidance,
                "blocked_by": "native-file-tool-policy",
                "recommended_tool": "write_file",
            }
        tier = (
            RiskTier.AUTO
            if self._trusted_shell_match(command)
            else classify_shell_command(command, self.allowed_shell_patterns)
        )
        self._log_tool("run_shell", command, tier)
        perm = self._check_shell_permission(command, tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            try:
                argv = shlex.split(command)
            except ValueError as e:
                return {"ok": False, "error": f"Invalid shell syntax: {e}"}
            if not argv:
                return {"ok": False, "error": "Empty command"}
            if _uses_shell_syntax(command):
                proc = await _create_shell_process(command, self.cwd)
            else:
                proc = await _create_exec_process(*argv, cwd=self.cwd)
            self._active_processes.add(proc)
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await proc.wait()
                return {"ok": False, "error": f"Command timed out after {timeout}s"}
            except asyncio.CancelledError:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await proc.wait()
                raise
            finally:
                self._active_processes.discard(proc)
            if self.show_tool_calls and tier >= RiskTier.CONFIRM:
                output_bytes = len(stdout) + len(stderr)
                status = "completed" if proc.returncode == 0 else f"exited {proc.returncode}"
                console.print(f"[dim]Shell command {status}; captured {output_bytes} bytes.[/dim]")
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
        perm = self._check_permission("Execute Python code snippet", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as handle:
                handle.write(code)
                tmp_path = handle.name
            proc = await _create_exec_process(sys.executable, tmp_path, cwd=self.cwd)
            self._active_processes.add(proc)
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await proc.wait()
                return {"ok": False, "error": f"Python execution timed out after {timeout}s"}
            except asyncio.CancelledError:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await proc.wait()
                raise
            finally:
                self._active_processes.discard(proc)
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
        """Install a Python package through the active interpreter's pip."""
        tier = RiskTier.CONFIRM
        pkg_spec = f"{package}=={version}" if version else package
        self._log_tool("install_package", pkg_spec, tier)

        module_name = package.replace("-", "_").split("[")[0]
        if importlib.util.find_spec(module_name) is not None:
            return {"ok": True, "already_installed": True, "package": pkg_spec}

        perm = self._check_permission(f"pip install {pkg_spec}  (required for this task)", tier)
        if not perm.approved:
            denied = self._permission_denied(perm)
            denied["package"] = pkg_spec
            return denied

        result = await self.run_shell(
            f"{sys.executable} -m pip install {pkg_spec} --quiet",
            timeout=120,
        )
        if result["ok"]:
            return {"ok": True, "installed": pkg_spec, "already_installed": False}
        return {"ok": False, "error": result.get("stderr", "pip failed"), "package": pkg_spec}

    async def search_codebase(self, pattern: str, path: str = ".") -> ToolResult:
        """Search project text with ripgrep, falling back to grep."""
        abs_path, tier = self._path_tier("read", path)
        self._log_tool("search_codebase", f"{pattern!r} in {abs_path}", tier)
        perm = self._check_permission(f"Search {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        search_command = shutil.which("rg") or shutil.which("grep")
        if not search_command:
            return {"ok": False, "error": "No search tool found (rg or grep)"}
        cmd = (
            ["rg", "--line-number", "--no-heading", pattern, str(abs_path)]
            if Path(search_command).name == "rg"
            else ["grep", "-rn", pattern, str(abs_path)]
        )
        try:
            proc = await _create_exec_process(*cmd, cwd=self.cwd)
            self._active_processes.add(proc)
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            finally:
                self._active_processes.discard(proc)
            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            return {
                "ok": True,
                "matches": lines[:100],
                "truncated": len(lines) > 100,
                "total": len(lines),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def git_op(self, subcommand: str, *args: str) -> ToolResult:
        """Run a Git subcommand through the shell permission policy."""
        command = f"git {subcommand} {' '.join(args)}"
        return await self.run_shell(command)


__all__ = [
    "ShellToolsMixin",
    "execute_plan_sandbox",
    "sandbox_plan_preview",
]
