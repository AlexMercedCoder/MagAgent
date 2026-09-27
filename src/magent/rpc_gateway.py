"""`magent serve --rpc`: a JSON-RPC 2.0 gateway for remote desktop clients.

This implements the contract Mag Command Center's remote transport speaks
(`src/lib/desktop.ts`): an HTTP POST of ``{"jsonrpc": "2.0", "id", "method",
"params"}`` with ``Authorization: Bearer <token>``, answered with ``result`` or
``error.message``. Method names match the desktop app's native commands where
the semantics are the same (``run_magent``, ``run_magent_input``,
``write_magent_stream``, ``cancel_magent_stream``, ``runtime_info``). Streaming
is added with ``stream.start`` + ``stream.events`` (long-poll) and a
Server-Sent-Events endpoint, because a single HTTP request cannot stay open for
a whole agent run within the client's 30 second timeout.

Protocol ``magent.rpc.v1`` (see docs/rpc-gateway.md for the full reference):

- ``POST /rpc``: JSON-RPC 2.0, one request per call (no batches).
- ``GET /rpc/streams/<id>/events?after=<seq>``: ``text/event-stream`` with
  ``event: stream`` records and a final ``event: done`` carrying the result.
- ``GET /healthz``: unauthenticated ``{"ok": true}`` liveness only.

Security model: a bearer token is required on every request except
``/healthz`` and is compared in constant time. The server binds to loopback
unless ``allow_remote`` is set; for anything else put it behind a TLS reverse
proxy. Requests, arguments and output are bounded; a small set of commands
that start servers or need a terminal are refused; ``--project`` values must
resolve inside the configured roots; every call is appended to an audit log
with secrets redacted; a token bucket limits request rate.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from magent import __version__

PROTOCOL = "magent.rpc.v1"
SCHEMA = "magent.rpc-gateway.v1"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_ARGS = 256
MAX_ARG_BYTES = 64 * 1024
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_STREAM_EVENTS = 5000
MAX_CONCURRENT_STREAMS = 4
MAX_WAIT_MS = 25_000
COMMAND_TIMEOUT_SECONDS = 600
TERMINATE_GRACE_SECONDS = 3.0

# Commands that start long-lived servers, need an interactive terminal, or
# would let a remote caller re-expose the machine. Checked against the first
# one or two argv words.
DENIED_COMMANDS = {
    ("serve",),
    ("ui",),
    ("setup",),
    ("configure",),
    ("dashboard",),
    ("daemon", "start"),
    ("gateway", "start"),
    ("memory", "ui"),
    ("mcp", "serve"),
}
SECRET_FLAGS = {"--api-key", "--token", "--password", "--secret"}

# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNAUTHORIZED = -32001
FORBIDDEN = -32003
NOT_FOUND = -32004
RATE_LIMITED = -32029
BUSY = -32030


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def magent_argv() -> list[str]:
    """How the gateway starts MagAgent: the same interpreter, `python -m magent`."""

    return [sys.executable, "-m", "magent"]


def redact_args(args: Iterable[str]) -> list[str]:
    out: list[str] = []
    hide_next = False
    for item in args:
        if hide_next:
            out.append("<redacted>")
            hide_next = False
            continue
        flag, _, value = item.partition("=")
        if flag in SECRET_FLAGS:
            out.append(f"{flag}=<redacted>" if value else flag)
            hide_next = not value
            continue
        out.append(item)
    return out


@dataclass
class StreamRun:
    id: str
    args: list[str]
    process: subprocess.Popen[bytes]
    started_at: float
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_STREAM_EVENTS))
    sequence: int = 0
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    output_bytes: int = 0
    result: dict[str, Any] | None = None
    changed: threading.Condition = field(default_factory=threading.Condition)

    def append(self, stream: str, line: str) -> None:
        with self.changed:
            self.sequence += 1
            self.events.append(
                {"seq": self.sequence, "id": self.id, "stream": stream, "line": line}
            )
            if stream in {"stdout", "stderr"} and self.output_bytes < MAX_OUTPUT_BYTES:
                self.output_bytes += len(line)
                (self.stdout if stream == "stdout" else self.stderr).append(line)
            self.changed.notify_all()

    def finish(self, result: dict[str, Any]) -> None:
        with self.changed:
            self.result = result
            self.changed.notify_all()

    def page(self, after: int) -> dict[str, Any]:
        with self.changed:
            events = [event for event in self.events if event["seq"] > after]
            oldest = self.events[0]["seq"] if self.events else self.sequence + 1
            return {
                "id": self.id,
                "events": events,
                "next": self.sequence,
                "gap": after + 1 < oldest and after < self.sequence,
                "done": self.result is not None,
                "result": self.result,
            }


class TokenBucket:
    def __init__(self, rate_per_minute: int) -> None:
        self.capacity = max(1, rate_per_minute)
        self.tokens = float(self.capacity)
        self.refill = self.capacity / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill)
            self.updated = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


class Gateway:
    """The request handlers, independent of the HTTP server (and so testable)."""

    def __init__(
        self,
        *,
        token: str,
        roots: list[Path],
        audit_path: Path | None = None,
        rate_per_minute: int = 240,
        command: Callable[[], list[str]] = magent_argv,
        env: dict[str, str] | None = None,
    ) -> None:
        if len(token) < 16:
            raise ValueError("the gateway token must be at least 16 characters")
        self.token = token
        self.roots = [Path(root).resolve() for root in roots] or [Path.cwd().resolve()]
        self.audit_path = audit_path
        self.bucket = TokenBucket(rate_per_minute)
        self.command = command
        self.env = env
        self.streams: dict[str, StreamRun] = {}
        self.lock = threading.Lock()
        self.audit_lock = threading.Lock()
        self.methods: dict[str, Callable[[dict[str, Any]], Any]] = {
            "runtime_info": self.runtime_info,
            "run_magent": self.run_magent,
            "run_magent_input": self.run_magent_input,
            "stream.start": self.stream_start,
            "stream.events": self.stream_events,
            "stream.list": self.stream_list,
            "write_magent_stream": self.write_magent_stream,
            "cancel_magent_stream": self.cancel_magent_stream,
        }

    # ------------------------------------------------------------ plumbing

    def authorized(self, header: str | None) -> bool:
        if not header or not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[7:].strip().encode(), self.token.encode())

    def audit(self, record: dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        entry = {"ts": datetime.now(UTC).isoformat(), **record}
        with self.audit_lock, contextlib.suppress(OSError):
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")

    def validate_args(self, params: dict[str, Any]) -> list[str]:
        args = params.get("args")
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise RpcError(INVALID_PARAMS, "params.args must be a list of strings")
        if len(args) > MAX_ARGS or any(len(item.encode()) > MAX_ARG_BYTES for item in args):
            raise RpcError(INVALID_PARAMS, "params.args exceeds the gateway limits")
        words = tuple(item for item in args if not item.startswith("-"))
        for denied in DENIED_COMMANDS:
            if words[: len(denied)] == denied:
                raise RpcError(
                    FORBIDDEN, f"`magent {' '.join(denied)}` is not available through the gateway"
                )
        for index, item in enumerate(args):
            value = None
            if item == "--project" and index + 1 < len(args):
                value = args[index + 1]
            elif item.startswith("--project="):
                value = item.split("=", 1)[1]
            if value is not None and not self._inside_roots(value):
                raise RpcError(
                    FORBIDDEN,
                    "--project must be inside the gateway's allowed roots",
                    {"roots": [str(root) for root in self.roots]},
                )
        return list(args)

    def _inside_roots(self, value: str) -> bool:
        path = Path(value)
        resolved = (path if path.is_absolute() else self.roots[0] / path).resolve()
        return any(resolved == root or resolved.is_relative_to(root) for root in self.roots)

    def _spawn(self, args: list[str], *, stdin: bool) -> subprocess.Popen[bytes]:
        kwargs: dict[str, Any] = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:  # pragma: no cover - Windows
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(  # noqa: S603 - argv list, no shell
            [*self.command(), *args],
            cwd=self.roots[0],
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            **kwargs,
        )

    def _command_string(self, args: list[str]) -> str:
        return " ".join(["magent", *redact_args(args)])

    # ------------------------------------------------------------- methods

    def runtime_info(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "protocol": PROTOCOL,
            "transport": "json-rpc-http",
            "version": __version__,
            "capabilities": ["commands", "streams", "approvals", "cancel", "events-sse"],
            "methods": sorted(self.methods),
            "roots": [str(root) for root in self.roots],
            "limits": {
                "max_body_bytes": MAX_BODY_BYTES,
                "max_args": MAX_ARGS,
                "max_concurrent_streams": MAX_CONCURRENT_STREAMS,
                "max_wait_ms": MAX_WAIT_MS,
                "command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            },
        }

    def run_magent(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._run_once(self.validate_args(params), None)

    def run_magent_input(self, params: dict[str, Any]) -> dict[str, Any]:
        args = self.validate_args(params)
        text = params.get("input")
        if not isinstance(text, str):
            raise RpcError(INVALID_PARAMS, "params.input must be a string")
        if len(text.encode()) > MAX_INPUT_BYTES:
            raise RpcError(INVALID_PARAMS, "params.input exceeds the 2 MiB limit")
        return self._run_once(args, text)

    def _run_once(self, args: list[str], text: str | None) -> dict[str, Any]:
        process = self._spawn(args, stdin=text is not None)
        try:
            stdout, stderr = process.communicate(
                input=text.encode() if text is not None else None,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            self._terminate(process)
            stdout, stderr = process.communicate()
            stderr += b"\nmagent gateway: command timed out"
        return {
            "ok": process.returncode == 0,
            "command": self._command_string(args),
            "stdout": stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
            "stderr": stderr[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
            "status": process.returncode,
        }

    def stream_start(self, params: dict[str, Any]) -> dict[str, Any]:
        args = self.validate_args(params)
        requested = params.get("id")
        stream_id = str(requested) if requested else uuid.uuid4().hex
        if not stream_id.replace("-", "").replace("_", "").isalnum() or len(stream_id) > 128:
            raise RpcError(INVALID_PARAMS, "params.id must be 1-128 letters, digits, - or _")
        with self.lock:
            active = [run for run in self.streams.values() if run.result is None]
            if len(active) >= MAX_CONCURRENT_STREAMS:
                raise RpcError(BUSY, f"at most {MAX_CONCURRENT_STREAMS} streams may run at once")
            if stream_id in self.streams:
                raise RpcError(INVALID_PARAMS, f"stream {stream_id} already exists")
            process = self._spawn(args, stdin=True)
            run = StreamRun(stream_id, args, process, time.time())
            self.streams[stream_id] = run
        run.append("status", "MagAgent process started")
        readers = [
            threading.Thread(target=self._pump, args=(run, process.stdout, "stdout"), daemon=True),
            threading.Thread(target=self._pump, args=(run, process.stderr, "stderr"), daemon=True),
        ]
        for reader in readers:
            reader.start()
        threading.Thread(target=self._reap, args=(run, readers), daemon=True).start()
        return {"id": stream_id, "command": self._command_string(args)}

    def _pump(self, run: StreamRun, pipe: Any, stream: str) -> None:
        with contextlib.suppress(Exception):
            for raw in iter(pipe.readline, b""):
                run.append(stream, raw.decode("utf-8", errors="replace").rstrip("\n"))
        with contextlib.suppress(Exception):
            pipe.close()

    def _reap(self, run: StreamRun, readers: list[threading.Thread]) -> None:
        try:
            status = run.process.wait(timeout=COMMAND_TIMEOUT_SECONDS * 6)
        except subprocess.TimeoutExpired:
            self._terminate(run.process)
            status = run.process.wait()
        for reader in readers:
            reader.join(timeout=5)
        with contextlib.suppress(Exception):
            if run.process.stdin:
                run.process.stdin.close()
        run.append(
            "status",
            "MagAgent process completed"
            if status == 0
            else "MagAgent process exited with an error",
        )
        run.finish(
            {
                "ok": status == 0,
                "command": self._command_string(run.args),
                "stdout": "\n".join(run.stdout),
                "stderr": "\n".join(run.stderr),
                "status": status,
            }
        )

    def _stream(self, params: dict[str, Any]) -> StreamRun:
        stream_id = str(params.get("id") or "")
        with self.lock:
            run = self.streams.get(stream_id)
        if run is None:
            raise RpcError(NOT_FOUND, f"no stream called {stream_id!r}")
        return run

    def stream_events(self, params: dict[str, Any]) -> dict[str, Any]:
        run = self._stream(params)
        after = int(params.get("after") or 0)
        wait_ms = max(0, min(int(params.get("wait_ms") or 0), MAX_WAIT_MS))
        deadline = time.monotonic() + wait_ms / 1000
        with run.changed:
            while run.sequence <= after and run.result is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                run.changed.wait(remaining)
        return run.page(after)

    def stream_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            runs = list(self.streams.values())
        return {
            "streams": [
                {
                    "id": run.id,
                    "command": self._command_string(run.args),
                    "started_at": run.started_at,
                    "done": run.result is not None,
                    "status": None if run.result is None else run.result["status"],
                }
                for run in runs
            ]
        }

    def write_magent_stream(self, params: dict[str, Any]) -> bool:
        from aais import validate

        run = self._stream(params)
        line = params.get("line")
        if not isinstance(line, str) or len(line.encode()) > MAX_INPUT_BYTES:
            raise RpcError(INVALID_PARAMS, "params.line must be a string under 2 MiB")
        try:
            envelope = validate(json.loads(line))
        except Exception as error:
            raise RpcError(INVALID_PARAMS, f"not a valid AAIS envelope: {error}") from error
        if envelope.get("type") != "approval.decided":
            raise RpcError(
                INVALID_PARAMS, "only approval.decided envelopes may be written to a running task"
            )
        if run.result is not None or run.process.stdin is None:
            raise RpcError(NOT_FOUND, "that stream is no longer running")
        try:
            run.process.stdin.write((json.dumps(envelope, separators=(",", ":")) + "\n").encode())
            run.process.stdin.flush()
        except OSError as error:
            raise RpcError(NOT_FOUND, f"the stream stopped reading input: {error}") from error
        return True

    def cancel_magent_stream(self, params: dict[str, Any]) -> bool:
        run = self._stream(params)
        if run.result is not None:
            return False
        run.append("status", "Cancellation requested")
        self._terminate(run.process)
        return True

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        """Stop the process and everything it started (its process group)."""

        if process.poll() is not None:
            return
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=TERMINATE_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - Windows
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )

    def shutdown(self) -> None:
        with self.lock:
            runs = list(self.streams.values())
        for run in runs:
            self._terminate(run.process)

    # ------------------------------------------------------------ dispatch

    def handle(self, body: bytes, authorization: str | None, peer: str = "") -> dict[str, Any]:
        """Handle one JSON-RPC request body and return the response object."""

        request_id: Any = None
        method = ""
        try:
            if not self.authorized(authorization):
                raise RpcError(UNAUTHORIZED, "missing or invalid bearer token")
            if not self.bucket.take():
                raise RpcError(RATE_LIMITED, "too many requests; slow down")
            try:
                request = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RpcError(PARSE_ERROR, f"invalid JSON: {error}") from error
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise RpcError(INVALID_REQUEST, "expected a single JSON-RPC 2.0 request object")
            request_id = request.get("id")
            method = str(request.get("method") or "")
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            handler = self.methods.get(method)
            if handler is None:
                raise RpcError(
                    METHOD_NOT_FOUND,
                    f"method {method!r} is not provided by the MagAgent gateway",
                    {"methods": sorted(self.methods)},
                )
            result = handler(params)
            self.audit(
                {
                    "peer": peer,
                    "method": method,
                    "args": redact_args(params.get("args") or []),
                    "stream": params.get("id"),
                    "ok": True,
                }
            )
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as error:
            self.audit({"peer": peer, "method": method, "ok": False, "error": error.message})
            return {"jsonrpc": "2.0", "id": request_id, "error": error.to_dict()}
        except Exception as error:  # never leak a traceback to the client
            self.audit({"peer": peer, "method": method, "ok": False, "error": "internal"})
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": INTERNAL_ERROR,
                    "message": f"internal error: {type(error).__name__}",
                },
            }


def _handler_class(gateway: Gateway) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"magent-rpc/{__version__}"
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802 - stdlib name
            if urlparse(self.path).path != "/rpc":
                self._send(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(
                    413 if length > MAX_BODY_BYTES else 400,
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": INVALID_REQUEST, "message": "missing or oversized body"},
                    },
                )
                return
            body = self.rfile.read(length)
            response = gateway.handle(
                body, self.headers.get("Authorization"), peer=self.client_address[0]
            )
            code = response.get("error", {}).get("code")
            # The desktop client treats any non-2xx as a transport failure, so
            # only authentication maps to an HTTP status; everything else is a
            # JSON-RPC error inside a 200.
            self._send(401 if code == UNAUTHORIZED else 200, response)

        def do_GET(self) -> None:  # noqa: N802 - stdlib name
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._send(200, {"ok": True, "protocol": PROTOCOL})
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["rpc", "streams"] or parts[3] != "events":
                self._send(404, {"error": "not found"})
                return
            if not gateway.authorized(self.headers.get("Authorization")):
                self._send(401, {"error": "missing or invalid bearer token"})
                return
            try:
                run = gateway._stream({"id": parts[2]})
            except RpcError as error:
                self._send(404, {"error": error.message})
                return
            after = int((parse_qs(parsed.query).get("after") or ["0"])[0] or 0)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    page = gateway.stream_events({"id": run.id, "after": after, "wait_ms": 15_000})
                    for event in page["events"]:
                        self.wfile.write(
                            f"id: {event['seq']}\nevent: stream\ndata: {json.dumps(event)}\n\n".encode()
                        )
                    after = page["next"]
                    if page["done"]:
                        self.wfile.write(
                            f"event: done\ndata: {json.dumps(page['result'])}\n\n".encode()
                        )
                        self.wfile.flush()
                        break
                    if not page["events"]:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            self.close_connection = True

    return Handler


def is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def serve_rpc(
    *,
    host: str = "127.0.0.1",
    port: int = 7850,
    token: str | None = None,
    roots: list[Path] | None = None,
    allow_remote: bool = False,
    audit_path: Path | None = None,
) -> tuple[ThreadingHTTPServer, Gateway, dict[str, Any]]:
    """Start the gateway on a background thread and return (server, gateway, info)."""

    if not is_loopback(host) and not allow_remote:
        raise ValueError(
            f"refusing to bind {host}: the gateway serves plain HTTP. Bind 127.0.0.1 and put a "
            "TLS reverse proxy in front, or pass --allow-remote if you understand the risk."
        )
    secret = token or secrets.token_urlsafe(32)
    gateway = Gateway(token=secret, roots=roots or [Path.cwd()], audit_path=audit_path)
    server = ThreadingHTTPServer((host, port), _handler_class(gateway))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="magent-rpc").start()
    bound_host, bound_port = server.server_address[:2]
    info = {
        "ok": True,
        "protocol": PROTOCOL,
        "url": f"http://{host if ':' not in str(host) else f'[{host}]'}:{bound_port}/rpc",
        "host": str(bound_host),
        "port": int(bound_port),
        "roots": [str(root) for root in gateway.roots],
        "audit_log": str(audit_path) if audit_path else None,
        "token_generated": token is None,
    }
    return server, gateway, info
