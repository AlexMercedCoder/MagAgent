"""One subprocess lifecycle, used everywhere.

`run_shell`, `run_python`, `search_codebase` and the workbench's three
`_run_command*` helpers each hand-rolled the same kill/await/timeout dance, and
they drifted: `search_codebase` had no timeout handler at all and orphaned its
child, and none of the workbench trio caught `TimeoutExpired`. Anything that
starts a process should use one of these.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = [
    "CompletedRun",
    "run_tracked",
    "run_tracked_sync",
    "terminate_process_tree",
]


class CompletedRun(dict[str, Any]):
    """A finished process, shaped like every other tool result."""

    @property
    def ok(self) -> bool:
        return bool(self.get("ok"))


def terminate_process_tree(process: subprocess.Popen[Any], *, force: bool = False) -> None:
    """Signal a process *and its group*.

    `start_new_session=True` puts a child in its own process group, but
    `terminate()`/`kill()` only reach the leader, so a shell task's children
    survived a cancel or a timeout.
    """
    group: int | None
    try:
        group = os.getpgid(process.pid)
    except (AttributeError, ProcessLookupError, OSError):
        group = None

    def send(sig: int) -> None:
        if group is not None:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(group, sig)
                return
        with contextlib.suppress(Exception):
            if sig == getattr(signal, "SIGKILL", signal.SIGTERM):
                process.kill()
            else:
                process.terminate()

    if not force:
        send(signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1.0)
            return
    send(getattr(signal, "SIGKILL", signal.SIGTERM))
    with contextlib.suppress(Exception):
        process.wait(timeout=2.0)


async def run_tracked(
    argv: Iterable[str],
    *,
    cwd: str | Path,
    timeout: int = 60,
    active: set[Any] | None = None,
    env: dict[str, str] | None = None,
    shell_command: str | None = None,
    stdout_limit: int = 0,
    stderr_limit: int = 0,
) -> CompletedRun:
    """Run a process to completion, always cleaning it up.

    On timeout or cancellation the child is killed and awaited rather than
    orphaned. Pass `shell_command` to run through a shell instead of argv.
    """
    argv = [str(item) for item in argv]

    if shell_command is not None:
        process = await asyncio.create_subprocess_shell(
            shell_command,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        label = shell_command
    else:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        label = " ".join(argv)

    if active is not None:
        active.add(process)

    async def cleanup() -> None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        with contextlib.suppress(Exception):
            await process.wait()

    try:
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            await cleanup()
            return CompletedRun(
                {
                    "ok": False,
                    "command": label,
                    "error": f"Command timed out after {timeout}s",
                    "timed_out": True,
                }
            )
        except asyncio.CancelledError:
            await cleanup()
            raise
    finally:
        if active is not None:
            active.discard(process)

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    return CompletedRun(
        {
            "ok": process.returncode == 0,
            "command": label,
            "returncode": process.returncode,
            "stdout": out[:stdout_limit] if stdout_limit else out,
            "stderr": err[:stderr_limit] if stderr_limit else err,
        }
    )


def run_tracked_sync(
    argv: Iterable[str],
    *,
    cwd: str | Path,
    timeout: int = 60,
    env: dict[str, str] | None = None,
    shell: bool = False,
    output_limit: int = 4000,
) -> CompletedRun:
    """Blocking counterpart for the synchronous call sites.

    A timeout becomes a structured result instead of a `TimeoutExpired`
    traceback surfacing from a CLI command.
    """
    command: Any = " ".join(str(item) for item in argv) if shell else [str(item) for item in argv]
    label = command if isinstance(command, str) else " ".join(command)
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return CompletedRun(
            {
                "ok": False,
                "command": label,
                "returncode": 124,
                "stdout": "",
                "stderr": f"timed out after {timeout}s",
                "timed_out": True,
            }
        )
    except (OSError, subprocess.SubprocessError) as error:
        return CompletedRun(
            {"ok": False, "command": label, "returncode": -1, "stdout": "", "stderr": str(error)}
        )

    return CompletedRun(
        {
            "ok": result.returncode == 0,
            "command": label,
            "returncode": result.returncode,
            "stdout": result.stdout[-output_limit:] if output_limit else result.stdout,
            "stderr": result.stderr[-output_limit:] if output_limit else result.stderr,
        }
    )
