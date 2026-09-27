"""Push notification for approval events, within and across processes (G-7).

Approvals used to be discovered by polling: waiting tools re-checked the store
every 100 ms and the Web UI re-fetched the pending snapshot every 800 ms.
Now:

* Every process that waits on a request, or watches the approval log (the Web
  UI server), opens a **doorbell**: a local datagram socket (a Unix socket in a
  private directory on POSIX, loopback UDP elsewhere). Its address is kept in
  the approval store's ``doorbells`` extension.
* Whoever writes an approval envelope **rings** every registered doorbell
  after the transaction commits. A ring carries no data; it only means "read
  the store". Dead doorbells are pruned when a ring cannot be delivered.
* Inside one process, an ``ApprovalEventBus`` fans envelopes out to streaming
  readers (the Web UI's ``/api/approvals/stream``) with a condition variable.

Polling remains only as a safety net (every few seconds), so a lost datagram
can delay a wake-up but never lose a decision: the durable store is still the
single source of truth.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import socket
import tempfile
import threading
import weakref
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

DOORBELLS = "doorbells"
SAFETY_POLL_SECONDS = 2.0
MAX_DOORBELLS = 64
_RING = b"approval"


def _socket_dir() -> Path:
    owner = os.getuid() if hasattr(os, "getuid") else "user"
    base = Path(tempfile.gettempdir()) / f"magent-doorbells-{owner}"
    base.mkdir(mode=0o700, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(base, 0o700)
    _sweep(base)
    return base


def _sweep(base: Path) -> None:
    """Remove sockets left by processes that died without closing them."""
    from magent.process_liveness import process_alive

    for path in base.glob("*.sock"):
        pid_text = path.name.split("-", 1)[0]
        if pid_text.isdigit() and not process_alive(int(pid_text)):
            with contextlib.suppress(OSError):
                path.unlink()


class Doorbell:
    """A socket this process can be woken on."""

    def __init__(self, kind: str = "waiter") -> None:
        self.kind = kind
        self.id = secrets.token_hex(8)
        self._closed = False
        self.path: Path | None = None
        self.address: Any = None
        if hasattr(socket, "AF_UNIX"):
            path = _socket_dir() / f"{os.getpid()}-{self.id}.sock"
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                sock.bind(str(path))  # fails if the temp path is too long
            except OSError:
                sock.close()
            else:
                self.family, self.path, self.sock, self.address = "unix", path, sock, str(path)
        if self.address is None:
            self.family = "udp"
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", 0))
            self.address = list(self.sock.getsockname())
        # Close the socket (and remove its file) when the doorbell is dropped,
        # even if nobody called close(): brokers are often short-lived.
        self._finalizer = weakref.finalize(self, _release, self.sock, self.path)

    def record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "family": self.family,
            "address": self.address,
            "pid": os.getpid(),
        }

    def wait(self, timeout: float) -> bool:
        """Block until rung (True) or ``timeout`` seconds pass (False); drains pending rings."""

        if self._closed:
            return False
        self.sock.settimeout(max(0.0, timeout))
        try:
            self.sock.recv(64)
        except (TimeoutError, OSError):
            return False
        self.sock.setblocking(False)
        with contextlib.suppress(BlockingIOError, OSError):
            while self.sock.recv(64):
                pass
        return True

    def poke(self) -> None:
        """Wake this doorbell from inside the same process."""

        ring_one(self.record())

    def close(self) -> None:
        self._closed = True
        self._finalizer()


def _release(sock: socket.socket, path: Path | None) -> None:
    with contextlib.suppress(OSError):
        sock.close()
    if path is not None:
        with contextlib.suppress(OSError):
            path.unlink()


def ring_one(record: dict[str, Any]) -> bool:
    """Send one ring; False when the doorbell is gone (the caller prunes it)."""

    try:
        if record.get("family") == "unix" and hasattr(socket, "AF_UNIX"):
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                sender.setblocking(False)
                sender.sendto(_RING, str(record["address"]))
        else:
            host, port = record["address"]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(_RING, (str(host), int(port)))
        return True
    except BlockingIOError:
        return True  # its queue is full: it has rings waiting already
    except (OSError, KeyError, TypeError, ValueError):
        return False


def ring_all(records: list[dict[str, Any]], *, skip: set[str] | None = None) -> list[str]:
    """Ring every doorbell except ``skip``; return the ids that could not be reached."""

    dead: list[str] = []
    for record in records:
        if skip and record.get("id") in skip:
            continue
        if not ring_one(record):
            dead.append(str(record.get("id")))
    return dead


class ApprovalEventBus:
    """In-process fan-out of approval envelopes to streaming readers."""

    def __init__(self, limit: int = 1000) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=limit)
        self._seen: set[tuple[str, int]] = set()
        self._changed = threading.Condition()
        self.version = 0

    def publish(self, envelope: dict[str, Any]) -> None:
        key = (str(envelope.get("stream") or ""), int(envelope.get("sequence") or 0))
        with self._changed:
            if key in self._seen:
                return
            self._seen.add(key)
            self._events.append(envelope)
            self.version += 1
            self._changed.notify_all()

    def nudge(self) -> None:
        """Wake readers without an envelope (for example after a remote ring)."""

        with self._changed:
            self.version += 1
            self._changed.notify_all()

    def wait(self, version: int, timeout: float) -> int:
        with self._changed:
            if self.version == version:
                self._changed.wait(timeout)
            return self.version


class DoorbellWatcher:
    """Turn rings from other processes into calls to ``on_ring`` (a daemon thread)."""

    def __init__(self, register: Callable[[Doorbell], None], on_ring: Callable[[], None]) -> None:
        self.doorbell = Doorbell(kind="watcher")
        self._stop = threading.Event()
        self._on_ring = on_ring
        register(self.doorbell)
        self._thread = threading.Thread(target=self._run, daemon=True, name="magent-doorbell")
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            # A timeout also refreshes: the safety net for a lost datagram.
            self.doorbell.wait(SAFETY_POLL_SECONDS)
            if self._stop.is_set():
                break
            with contextlib.suppress(Exception):
                self._on_ring()

    def close(self) -> None:
        self._stop.set()
        self.doorbell.poke()
        self._thread.join(timeout=2)
        self.doorbell.close()
