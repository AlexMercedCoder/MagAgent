"""Authenticated, local-only messaging between live MagAgent sessions."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import socket
import struct
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent import config as magent_config

MAX_MESSAGE_BYTES = 8_000
MAX_WIRE_BYTES = 16_384
MAX_QUEUE_ITEMS = 200
MAX_HOPS = 3
MESSAGE_TTL_SECONDS = 24 * 60 * 60
PEER_TTL_SECONDS = 12 * 60 * 60
RATE_LIMIT_PER_MINUTE = 20
VALID_POLICIES = {"accept", "hold", "refuse"}
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def messaging_root() -> Path:
    return Path(magent_config.CONFIG_DIR) / "messaging"


def _user_key(username: str) -> str:
    return hashlib.sha256(username.encode("utf-8")).hexdigest()[:20]


def _paths(username: str) -> dict[str, Path]:
    root = messaging_root() / _user_key(username)
    uid = os.getuid() if hasattr(os, "getuid") else os.getpid()
    # Prefer the conventional short POSIX runtime prefix because AF_UNIX paths
    # are commonly capped near 100 bytes and TMPDIR may itself be deeply nested.
    temp_root = Path("/tmp") if os.name == "posix" and Path("/tmp").is_dir() else Path(tempfile.gettempdir())
    runtime = temp_root / f"magent-{uid}-{_user_key(username)}"
    return {
        "root": root,
        "peers": root / "peers",
        # Unix socket paths have a small platform limit, so runtime endpoints
        # use a short owner-only directory while durable state stays in config.
        "runtime": runtime,
        "inbox": root / "inbox",
        "held": root / "held",
        "outbox": root / "outbox",
        "receipts": root / "receipts",
        "seen": root / "seen",
    }


def _ensure_dirs(username: str) -> dict[str, Path]:
    paths = _paths(username)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            path.chmod(0o700)
    return paths


def _safe_id(value: str, label: str = "session ID") -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"Invalid {label}: use 1-96 letters, numbers, dots, dashes, or underscores")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{secrets.token_hex(4)}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    with contextlib.suppress(OSError):
        temp.chmod(0o600)
    temp.replace(path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, default=str) + "\n")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def _append_bounded_jsonl(path: Path, value: dict[str, Any]) -> None:
    _append_jsonl(path, value)
    items = _read_jsonl(path)
    if len(items) > MAX_QUEUE_ITEMS:
        _replace_jsonl(path, items[-MAX_QUEUE_ITEMS:])


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def _replace_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item, default=str) + "\n" for item in items[-MAX_QUEUE_ITEMS:])
    temp.write_text(text, encoding="utf-8")
    with contextlib.suppress(OSError):
        temp.chmod(0o600)
    temp.replace(path)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _peer_is_live(peer: dict[str, Any]) -> bool:
    try:
        registered = datetime.fromisoformat(str(peer.get("registered_at"))).timestamp()
    except (TypeError, ValueError):
        return False
    if time.time() - registered > PEER_TTL_SECONDS:
        return False
    return _pid_alive(int(peer.get("pid") or 0)) and bool(peer.get("endpoint"))


def list_sessions(username: str, *, include_stale: bool = False) -> list[dict[str, Any]]:
    """List authenticated peer roster entries for one MagAgent user."""
    paths = _ensure_dirs(username)
    peers: list[dict[str, Any]] = []
    for path in sorted(paths["peers"].glob("*.json")):
        item = _read_json(path)
        live = _peer_is_live(item)
        if not live and not include_stale:
            with contextlib.suppress(OSError):
                path.unlink()
            endpoint = Path(str(item.get("endpoint") or ""))
            if item.get("transport") == "unix" and endpoint:
                with contextlib.suppress(OSError):
                    endpoint.unlink()
            continue
        public = {key: value for key, value in item.items() if key != "capability"}
        public["live"] = live
        peers.append(public)
    return peers


def resolve_session(username: str, target: str) -> dict[str, Any]:
    """Resolve an exact durable ID or an unambiguous display alias."""
    _safe_id(target, "target")
    paths = _ensure_dirs(username)
    exact = _read_json(paths["peers"] / f"{target}.json")
    if exact and _peer_is_live(exact):
        return exact
    matches = [peer for peer in list_sessions(username) if peer.get("name") == target]
    if len(matches) > 1:
        raise ValueError(f"Session alias '{target}' is ambiguous; use a durable session ID")
    if len(matches) == 1:
        return _read_json(paths["peers"] / f"{matches[0]['session_id']}.json")
    raise ValueError(f"Session '{target}' is not reachable")


def _socket_peer_uid(conn: socket.socket) -> int | None:
    if os.name != "posix" or not hasattr(socket, "SO_PEERCRED"):
        return None
    try:
        _pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return int(uid)
    except OSError:
        return None


def _send_wire(peer: dict[str, Any], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    transport = peer.get("transport")
    if transport == "unix":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        address: Any = str(peer["endpoint"])
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        host, port = str(peer["endpoint"]).rsplit(":", 1)
        address = (host, int(port))
    try:
        sock.settimeout(timeout)
        sock.connect(address)
        sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        data = b""
        while b"\n" not in data and len(data) <= MAX_WIRE_BYTES:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        response = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
        return response if isinstance(response, dict) else {"status": "unreachable"}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "unreachable", "error": str(exc)}
    finally:
        sock.close()


def send_session_message(
    username: str,
    sender_id: str,
    target: str,
    message: str,
    *,
    task_id: str = "",
    hops: int = 0,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Deliver a bounded plain-text envelope and persist its receipt."""
    sender_id = _safe_id(sender_id)
    text = "".join(
        character
        for character in str(message)
        if character in {"\n", "\t"} or ord(character) >= 32
    ).strip()
    if not text:
        return {"ok": False, "status": "refused", "error": "Message must not be empty"}
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return {"ok": False, "status": "refused", "error": f"Message exceeds {MAX_MESSAGE_BYTES} bytes"}
    if hops >= MAX_HOPS:
        return {"ok": False, "status": "refused", "error": "Message hop limit reached"}
    paths = _ensure_dirs(username)
    sender = _read_json(paths["peers"] / f"{sender_id}.json")
    if not sender or not secrets.compare_digest(str(sender.get("username") or ""), username):
        return {"ok": False, "status": "refused", "error": "Sender is not registered"}
    message_id = secrets.token_hex(16)
    envelope = {
        "version": 1,
        "message_id": message_id,
        "nonce": secrets.token_hex(16),
        "timestamp": _now(),
        "expires_at": datetime.fromtimestamp(time.time() + MESSAGE_TTL_SECONDS, UTC).isoformat(),
        "sender_id": sender_id,
        "sender_name": sender.get("name") or sender_id,
        "sender_capability": sender.get("capability"),
        "reply_to": sender_id,
        "project": sender.get("project") or "",
        "cwd": sender.get("cwd") or "",
        "task_id": str(task_id)[:128],
        "provenance": "magent-local-peer",
        "hops": hops + 1,
        "message": text,
    }
    pending = {"event": "pending", "target": target, "envelope": envelope, "ts": _now()}
    outbox_path = paths["outbox"] / f"{sender_id}.jsonl"
    _append_bounded_jsonl(outbox_path, pending)
    try:
        peer = resolve_session(username, target)
    except ValueError as exc:
        peer = {}
        response = {"status": "unreachable", "error": str(exc)}
    else:
        response = _send_wire(
            peer,
            {"capability": peer.get("capability"), "envelope": envelope},
            timeout,
        )
    receipt = {
        "ok": response.get("status") in {"delivered", "held"},
        "message_id": message_id,
        "sender_id": sender_id,
        "target_id": peer.get("session_id") or target,
        "status": response.get("status", "unreachable"),
        "reason": str(response.get("reason") or response.get("error") or "")[:300],
        "source_project": sender.get("project") or "",
        "target_project": peer.get("project") or "",
        "cross_project": bool(
            sender.get("project") and peer.get("project") and sender.get("project") != peer.get("project")
        ),
        "ts": _now(),
    }
    _append_bounded_jsonl(paths["receipts"] / f"{sender_id}.jsonl", receipt)
    _append_bounded_jsonl(outbox_path, {"event": "receipt", **receipt})
    return receipt


def session_receipts(username: str, sender_id: str) -> list[dict[str, Any]]:
    """Return durable delivery receipts for a sender."""
    paths = _ensure_dirs(username)
    return _read_jsonl(paths["receipts"] / f"{_safe_id(sender_id)}.jsonl")


def messaging_diagnostics(username: str, config: Any | None = None) -> dict[str, Any]:
    """Return local transport, policy, roster, and queue health without binding a socket."""
    enabled = bool(config.get("session_messaging", "enabled", default=True)) if config else True
    policy = str(config.get("session_messaging", "policy", default="accept")) if config else "accept"
    paths = _ensure_dirs(username)
    peers = list_sessions(username)
    held_count = sum(len(_read_jsonl(path)) for path in paths["held"].glob("*.jsonl"))
    outbox_count = 0
    for path in paths["outbox"].glob("*.jsonl"):
        records = _read_jsonl(path)
        pending_ids = {
            str(item.get("envelope", {}).get("message_id"))
            for item in records
            if item.get("event") == "pending" and isinstance(item.get("envelope"), dict)
        }
        statuses = {
            str(item.get("message_id")): str(item.get("status"))
            for item in records
            if item.get("event") == "receipt"
        }
        outbox_count += sum(
            1 for message_id in pending_ids if statuses.get(message_id) in {None, "unreachable"}
        )
    permissions_ok = all(
        not path.exists() or (path.stat().st_mode & 0o077) == 0
        for path in (paths["root"], paths["peers"], paths["runtime"])
    )
    return {
        "ok": policy in VALID_POLICIES and permissions_ok,
        "enabled": enabled,
        "policy": policy,
        "headless_accept": bool(
            config.get("session_messaging", "headless_accept", default=False)
        )
        if config
        else False,
        "transport": "unix" if hasattr(socket, "AF_UNIX") and os.name != "nt" else "tcp",
        "live_sessions": len(peers),
        "held_messages": held_count,
        "pending_outbox_records": outbox_count,
        "owner_only_storage": permissions_ok,
        "root": str(paths["root"]),
    }


def retry_outbox(username: str, sender_id: str, *, timeout: float = 3.0) -> dict[str, Any]:
    """Retry currently unreachable, unexpired messages from a live sender."""
    sender_id = _safe_id(sender_id)
    paths = _ensure_dirs(username)
    sender = _read_json(paths["peers"] / f"{sender_id}.json")
    if not sender or not _peer_is_live(sender):
        return {"ok": False, "retried": 0, "error": "Sender must be a live registered session"}
    outbox_path = paths["outbox"] / f"{sender_id}.jsonl"
    records = _read_jsonl(outbox_path)
    pending = {
        str(item.get("envelope", {}).get("message_id")): item
        for item in records
        if item.get("event") == "pending" and isinstance(item.get("envelope"), dict)
    }
    terminal = {
        str(item.get("message_id")): str(item.get("status"))
        for item in records
        if item.get("event") == "receipt"
    }
    results: list[dict[str, Any]] = []
    for message_id, record in pending.items():
        if terminal.get(message_id) not in {None, "unreachable"}:
            continue
        envelope = dict(record["envelope"])
        envelope["sender_capability"] = sender.get("capability")
        try:
            expires = datetime.fromisoformat(str(envelope.get("expires_at"))).timestamp()
        except (TypeError, ValueError):
            expires = 0
        if time.time() > expires:
            response = {"status": "expired", "reason": "Message expired before retry"}
        else:
            try:
                peer = resolve_session(username, str(record.get("target") or ""))
            except ValueError as exc:
                response = {"status": "unreachable", "reason": str(exc)}
            else:
                response = _send_wire(
                    peer,
                    {"capability": peer.get("capability"), "envelope": envelope},
                    timeout,
                )
        receipt = {
            "event": "receipt",
            "ok": response.get("status") in {"delivered", "held"},
            "message_id": message_id,
            "sender_id": sender_id,
            "target_id": record.get("target"),
            "status": response.get("status", "unreachable"),
            "reason": str(response.get("reason") or response.get("error") or "")[:300],
            "ts": _now(),
            "retry": True,
        }
        _append_bounded_jsonl(outbox_path, receipt)
        _append_bounded_jsonl(paths["receipts"] / f"{sender_id}.jsonl", receipt)
        results.append(receipt)
    return {"ok": all(item.get("ok") for item in results), "retried": len(results), "receipts": results}


def session_inbox(username: str, session_id: str, *, held: bool = False) -> list[dict[str, Any]]:
    paths = _ensure_dirs(username)
    bucket = "held" if held else "inbox"
    path = paths[bucket] / f"{_safe_id(session_id)}.jsonl"
    items = _read_jsonl(path)
    if held:
        active = [item for item in items if not _message_expired(item)]
        if len(active) != len(items):
            _replace_jsonl(path, active)
        return active
    return items


def _message_expired(item: dict[str, Any]) -> bool:
    try:
        return time.time() > datetime.fromisoformat(str(item.get("expires_at"))).timestamp()
    except (TypeError, ValueError):
        return True


def review_held_message(username: str, session_id: str, message_id: str, decision: str) -> dict[str, Any]:
    """Accept or refuse one held message."""
    if decision not in {"accept", "refuse"}:
        raise ValueError("decision must be accept or refuse")
    paths = _ensure_dirs(username)
    held_path = paths["held"] / f"{_safe_id(session_id)}.jsonl"
    items = _read_jsonl(held_path)
    selected = next((item for item in items if item.get("message_id") == message_id), None)
    if selected is None:
        return {"ok": False, "error": "Held message not found"}
    _replace_jsonl(held_path, [item for item in items if item.get("message_id") != message_id])
    if _message_expired(selected):
        return {"ok": False, "message_id": message_id, "status": "expired"}
    if decision == "accept":
        selected["reviewed_at"] = _now()
        _append_bounded_jsonl(paths["inbox"] / f"{session_id}.jsonl", selected)
    return {"ok": True, "message_id": message_id, "status": "delivered" if decision == "accept" else "refused"}


class SessionMessenger:
    """Own a live peer endpoint and durable inbox for an AgentSession."""

    def __init__(
        self,
        username: str,
        session_id: str,
        *,
        name: str = "",
        cwd: str = "",
        project: str = "",
        policy: str = "accept",
        headless: bool = False,
        headless_accept: bool = False,
        on_message: Callable[[dict[str, Any], str], None] | None = None,
        transport: str = "",
    ) -> None:
        self.username = username
        self.session_id = _safe_id(session_id)
        self.name = _safe_id(name or session_id, "session name")
        self.cwd = str(Path(cwd).resolve(strict=False)) if cwd else ""
        self.project = project
        self.policy = policy if policy in VALID_POLICIES else "hold"
        if headless and self.policy == "accept" and not headless_accept:
            self.policy = "hold"
        self.on_message = on_message
        self.capability = secrets.token_urlsafe(32)
        self.paths = _ensure_dirs(username)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._seen: set[str] = set()
        self._rate: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        digest = hashlib.sha256(session_id.encode()).hexdigest()[:24]
        self.transport = transport or ("unix" if hasattr(socket, "AF_UNIX") and os.name != "nt" else "tcp")
        if self.transport not in {"unix", "tcp"}:
            raise ValueError("transport must be unix or tcp")
        self.endpoint = str(self.paths["runtime"] / f"{digest}.sock") if self.transport == "unix" else ""
        for bucket in ("inbox", "held", "seen"):
            queued = _read_jsonl(self.paths[bucket] / f"{self.session_id}.jsonl")
            self._seen.update(str(item.get("message_id")) for item in queued if item.get("message_id"))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self.transport == "unix":
            with contextlib.suppress(OSError):
                Path(self.endpoint).unlink()
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(self.endpoint)
            except Exception:
                server.close()
                raise
            with contextlib.suppress(OSError):
                Path(self.endpoint).chmod(0o600)
        else:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(("127.0.0.1", 0))
            host, port = server.getsockname()[:2]
            self.endpoint = f"{host}:{port}"
        server.listen(8)
        server.settimeout(0.25)
        self._socket = server
        self._register()
        self._thread = threading.Thread(target=self._serve, name=f"magent-peer-{self.session_id}", daemon=True)
        self._thread.start()
        # Recover delivery attempts that may have been interrupted while this
        # durable session ID was offline.
        retry_outbox(self.username, self.session_id)

    def _register(self) -> None:
        _atomic_json(
            self.paths["peers"] / f"{self.session_id}.json",
            {
                "version": 1,
                "session_id": self.session_id,
                "name": self.name,
                "username": self.username,
                "pid": os.getpid(),
                "uid": os.getuid() if hasattr(os, "getuid") else None,
                "cwd": self.cwd,
                "project": self.project,
                "transport": self.transport,
                "endpoint": self.endpoint,
                "capability": self.capability,
                "policy": self.policy,
                "registered_at": _now(),
            },
        )

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                conn, _address = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(2)
                response = self._receive(conn)
                with contextlib.suppress(OSError):
                    conn.sendall(json.dumps(response).encode("utf-8") + b"\n")

    def _receive(self, conn: socket.socket) -> dict[str, Any]:
        peer_uid = _socket_peer_uid(conn) if self.transport == "unix" else None
        if peer_uid is not None and hasattr(os, "getuid") and peer_uid != os.getuid():
            return {"status": "refused", "reason": "OS user mismatch"}
        data = b""
        try:
            while b"\n" not in data and len(data) <= MAX_WIRE_BYTES:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if len(data) > MAX_WIRE_BYTES:
                return {"status": "refused", "reason": "Envelope too large"}
            payload = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"status": "refused", "reason": "Malformed envelope"}
        if not isinstance(payload, dict) or not secrets.compare_digest(str(payload.get("capability") or ""), self.capability):
            return {"status": "refused", "reason": "Authentication failed"}
        envelope = payload.get("envelope")
        if not isinstance(envelope, dict):
            return {"status": "refused", "reason": "Missing envelope"}
        return self._accept_envelope(envelope)

    def _accept_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        sender_id = str(envelope.get("sender_id") or "")
        message_id = str(envelope.get("message_id") or "")
        sender = _read_json(self.paths["peers"] / f"{sender_id}.json") if _ID_RE.fullmatch(sender_id) else {}
        if not sender or not secrets.compare_digest(
            str(sender.get("capability") or ""), str(envelope.get("sender_capability") or "")
        ):
            return {"status": "refused", "reason": "Sender authentication failed"}
        try:
            expires = datetime.fromisoformat(str(envelope.get("expires_at"))).timestamp()
        except (TypeError, ValueError):
            return {"status": "refused", "reason": "Invalid expiry"}
        if time.time() > expires:
            return {"status": "expired", "reason": "Message expired"}
        if int(envelope.get("hops") or 0) > MAX_HOPS:
            return {"status": "refused", "reason": "Hop limit exceeded"}
        text = str(envelope.get("message") or "")
        if not text or len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
            return {"status": "refused", "reason": "Invalid message body"}
        if self.policy == "refuse":
            return {"status": "refused", "reason": "Receiver policy refuses peer messages"}
        bucket = "held" if self.policy == "hold" else "inbox"
        path = self.paths[bucket] / f"{self.session_id}.jsonl"
        with self._lock:
            if message_id in self._seen:
                return {"status": "delivered", "reason": "Duplicate suppressed"}
            now = time.time()
            recent = [stamp for stamp in self._rate.get(sender_id, []) if now - stamp < 60]
            if len(recent) >= RATE_LIMIT_PER_MINUTE:
                return {"status": "refused", "reason": "Peer rate limit exceeded"}
            if len(_read_jsonl(path)) >= MAX_QUEUE_ITEMS:
                return {"status": "refused", "reason": "Receiver queue is full"}
            recent.append(now)
            self._rate[sender_id] = recent
            self._seen.add(message_id)
            _append_bounded_jsonl(
                self.paths["seen"] / f"{self.session_id}.jsonl",
                {"message_id": message_id, "received_at": _now()},
            )
            if len(self._seen) > MAX_QUEUE_ITEMS * 2:
                self._seen = set(list(self._seen)[-MAX_QUEUE_ITEMS:])
        safe = {
            key: envelope.get(key)
            for key in (
                "version", "message_id", "nonce", "timestamp", "expires_at", "sender_id",
                "sender_name", "reply_to", "project", "cwd", "task_id", "provenance", "hops", "message",
            )
        }
        safe["received_at"] = _now()
        safe["trust"] = "untrusted-peer-text"
        _append_bounded_jsonl(path, safe)
        status = "held" if self.policy == "hold" else "delivered"
        if self.on_message:
            with contextlib.suppress(Exception):
                self.on_message(safe, status)
        return {"status": status, "message_id": message_id}

    def drain(self) -> list[dict[str, Any]]:
        path = self.paths["inbox"] / f"{self.session_id}.jsonl"
        with self._lock:
            items = _read_jsonl(path)
            _replace_jsonl(path, [])
        return items

    def send(self, target: str, message: str, *, task_id: str = "", hops: int = 0) -> dict[str, Any]:
        return send_session_message(
            self.username, self.session_id, target, message, task_id=task_id, hops=hops
        )

    def peers(self) -> list[dict[str, Any]]:
        return [peer for peer in list_sessions(self.username) if peer.get("session_id") != self.session_id]

    def stop(self) -> None:
        self._stop.set()
        if self._socket:
            with contextlib.suppress(OSError):
                self._socket.close()
        if self._thread:
            self._thread.join(timeout=1)
        with contextlib.suppress(OSError):
            (self.paths["peers"] / f"{self.session_id}.json").unlink()
        if self.transport == "unix":
            with contextlib.suppress(OSError):
                Path(self.endpoint).unlink()


def register_ephemeral_sender(username: str, *, name: str = "cli", cwd: str = "") -> tuple[str, Callable[[], None]]:
    """Register a short-lived authenticated sender for CLI delivery."""
    session_id = f"cli_{os.getpid()}_{secrets.token_hex(4)}"
    paths = _ensure_dirs(username)
    path = paths["peers"] / f"{session_id}.json"
    _atomic_json(
        path,
        {
            "version": 1,
            "session_id": session_id,
            "name": _safe_id(name, "session name"),
            "username": username,
            "pid": os.getpid(),
            "cwd": str(Path(cwd or os.getcwd()).resolve()),
            "project": Path(cwd or os.getcwd()).name,
            "transport": "ephemeral",
            "endpoint": "ephemeral",
            "capability": secrets.token_urlsafe(32),
            "policy": "refuse",
            "registered_at": _now(),
        },
    )
    return session_id, lambda: path.unlink(missing_ok=True)
