"""JSON-backed workbench storage primitives.

This underpins tasks, plans, checkpoints, patch records and session records, so
it should be the most durable code in the project. It previously was not:

* `write()` truncated the file and wrote in place, with no temp file, no
  `os.replace` and no fsync. A crash or a full disk mid-write left truncated
  JSON.
* `read()` caught every exception and returned the caller's default, so the
  next `read("tasks", [])` quietly returned `[]` and the next `append()`
  rewrote the file with a single item. Every prior task was gone, with no error
  anywhere.
* Nothing was locked, so `magent daemon run-once` and an interactive command
  could interleave read-modify-write cycles, mint duplicate ids and lose
  writes.

Writes are now atomic, corrupt files are preserved and reported rather than
silently swallowed, and read-modify-write cycles hold an advisory lock.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent.config import USERS_DIR

WORKBENCH_DIRNAME = "workbench"

# How long to wait for another process to finish a read-modify-write cycle.
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_RETRY_SECONDS = 0.02
# A lock file older than this is treated as abandoned by a crashed process.
LOCK_STALE_SECONDS = 60.0

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class WorkbenchStoreError(RuntimeError):
    """Raised when stored data cannot be read and must not be silently replaced."""


def _quarantine(path: Path, error: Exception) -> Path:
    """Move an unreadable file aside so the next write cannot erase it."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    target = path.with_suffix(f".json.corrupt-{stamp}")
    with contextlib.suppress(OSError):
        path.replace(target)
    return target


class WorkbenchStore:
    """Simple JSON-backed store scoped to one MagAgent user."""

    # Class-level default so instances built with __new__ (some tests, and any
    # caller that skips __init__) still have somewhere to record warnings.
    warnings: list[str] = []

    def __init__(self, username: str):
        self.username = username
        self.root = USERS_DIR / username / WORKBENCH_DIRNAME
        self.root.mkdir(parents=True, exist_ok=True)
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ paths

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def _lock_path(self, name: str) -> Path:
        return self.root / f".{name}.lock"

    # ------------------------------------------------------------------- io

    def read(self, name: str, default: Any, *, strict: bool = False) -> Any:
        path = self._path(name)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            if strict:
                raise WorkbenchStoreError(f"Stored state requires recovery: {path}") from error
            # Do not hand back `default`: the caller will write it straight
            # back and the real data is gone for good.
            target = _quarantine(path, error)
            message = f"{path.name} was unreadable ({error}); moved to {target.name}"
            self.warnings.append(message)
            return default
        except OSError as error:
            raise WorkbenchStoreError(f"Could not read {path}: {error}") from error

    def write(self, name: str, data: Any) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, default=str)

        # temp file → fsync → atomic replace. A reader always sees either the
        # previous file or the complete new one, never a truncated middle.
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                temp.unlink()
            raise

        # Durably record the rename itself.
        with contextlib.suppress(OSError, AttributeError):
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    # ---------------------------------------------------------------- locking

    @contextlib.contextmanager
    def lock(self, name: str) -> Iterator[None]:
        """Hold an advisory lock across a read-modify-write cycle."""
        path = self._lock_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is None:  # pragma: no cover - exercised by Windows CI
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
            while True:
                try:
                    if fcntl is None:  # pragma: no cover
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if time.monotonic() >= deadline:
                        raise WorkbenchStoreError(f"Timed out waiting for {path.name}") from error
                    time.sleep(LOCK_RETRY_SECONDS)
            yield
        finally:
            with contextlib.suppress(OSError):
                if fcntl is None:  # pragma: no cover
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def mutate(self, name: str, default: Any, change: Callable[[Any], Any]) -> Any:
        """Run a read-modify-write cycle under the lock.

        `change` receives the current value and returns `(new_value, result)`,
        or just the new value.
        """
        with self.lock(name):
            current = self.read(name, default)
            outcome = change(current)
            if isinstance(outcome, tuple) and len(outcome) == 2:
                new_value, result = outcome
            else:
                new_value, result = outcome, None
            self.write(name, new_value)
            return result

    # ------------------------------------------------------------ collections

    def append(self, name: str, item: dict[str, Any]) -> dict[str, Any]:
        def change(data: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            record = {"id": _next_id(data, _singular(name)), "created_at": now_iso(), **item}
            data.append(record)
            return data, record

        return self.mutate(name, [], change)

    def update_item(self, name: str, item_id: str, **updates: Any) -> dict[str, Any] | None:
        def change(
            data: list[dict[str, Any]],
        ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
            for record in data:
                if record.get("id") == item_id:
                    record.update(updates)
                    record["updated_at"] = now_iso()
                    return data, record
            return data, None

        return self.mutate(name, [], change)


def _singular(name: str) -> str:
    """`tasks` → `task`. `removesuffix`, not `rstrip`, which ate every trailing s."""
    return name.removesuffix("s")


def _next_id(items: list[dict[str, Any]], prefix: str) -> str:
    existing = [
        int(str(item.get("id", "")).rsplit("_", 1)[-1])
        for item in items
        if str(item.get("id", "")).rsplit("_", 1)[-1].isdigit()
    ]
    return f"{prefix}_{(max(existing) if existing else 0) + 1:04d}"
