"""Small synchronous JSON-RPC client for local Language Server Protocol processes."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class LspError(RuntimeError):
    """Raised when an LSP process or request fails."""


@dataclass(frozen=True)
class LspServerSpec:
    language: str
    command: tuple[str, ...]
    extensions: tuple[str, ...]


@dataclass
class LspClient:
    command: list[str]
    root: Path
    timeout: float = 10.0
    initialization_options: dict[str, Any] = field(default_factory=dict)
    process: subprocess.Popen[bytes] | None = field(default=None, init=False)
    capabilities: dict[str, Any] = field(default_factory=dict, init=False)
    _next_id: int = field(default=1, init=False)
    _pending: dict[int, queue.Queue[dict[str, Any]]] = field(default_factory=dict, init=False)
    _notifications: queue.Queue[dict[str, Any]] = field(default_factory=queue.Queue, init=False)
    _write_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _reader: threading.Thread | None = field(default=None, init=False)
    _stderr_reader: threading.Thread | None = field(default=None, init=False)
    _stderr_lines: deque[str] = field(default_factory=lambda: deque(maxlen=50), init=False)
    _reader_error: str = field(default="", init=False)
    _documents: dict[str, int] = field(default_factory=dict, init=False)

    def start(self) -> dict[str, Any]:
        if self.process and self.process.poll() is None:
            return self.capabilities
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise LspError(f"Could not start {' '.join(self.command)}: {exc}") from exc
        self._reader_error = ""
        self._reader = threading.Thread(
            target=self._read_loop, name="magent-lsp-reader", daemon=True
        )
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._read_stderr, name="magent-lsp-stderr", daemon=True
        )
        self._stderr_reader.start()
        result = self.request(
            "initialize",
            {
                "processId": None,
                "clientInfo": {"name": "MagAgent", "version": "0.60.0"},
                "rootUri": self.root.as_uri(),
                "workspaceFolders": [{"uri": self.root.as_uri(), "name": self.root.name}],
                "initializationOptions": self.initialization_options,
                "capabilities": {
                    "workspace": {"symbol": {"dynamicRegistration": False}},
                    "textDocument": {
                        "synchronization": {"didSave": True},
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "rename": {"prepareSupport": True},
                        "publishDiagnostics": {"relatedInformation": True},
                    },
                },
            },
        )
        self.capabilities = dict((result or {}).get("capabilities") or {})
        self.notify("initialized", {})
        return self.capabilities

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._ensure_running()
        request_id = self._next_id
        self._next_id += 1
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._pending[request_id] = response_queue
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        try:
            response = response_queue.get(timeout=self.timeout)
        except queue.Empty as exc:
            self.cancel(request_id)
            raise LspError(f"LSP request timed out after {self.timeout:g}s: {method}") from exc
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            error = response.get("error") or {}
            raise LspError(f"LSP {method} failed: {error.get('message') or error}")
        return response.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._ensure_running()
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def cancel(self, request_id: int) -> None:
        if self.process and self.process.poll() is None:
            self._send(
                {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": request_id}}
            )

    def open_document(self, path: str | Path, language_id: str) -> str:
        target = Path(path).resolve()
        uri = target.as_uri()
        text = target.read_text(encoding="utf-8", errors="replace")
        self._documents[uri] = 1
        self.notify(
            "textDocument/didOpen",
            {"textDocument": {"uri": uri, "languageId": language_id, "version": 1, "text": text}},
        )
        return uri

    def change_document(self, path: str | Path, text: str) -> None:
        uri = Path(path).resolve().as_uri()
        version = self._documents.get(uri, 0) + 1
        self._documents[uri] = version
        self.notify(
            "textDocument/didChange",
            {"textDocument": {"uri": uri, "version": version}, "contentChanges": [{"text": text}]},
        )

    def close_document(self, path: str | Path) -> None:
        uri = Path(path).resolve().as_uri()
        if uri in self._documents:
            self.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
            self._documents.pop(uri, None)

    def wait_for_notification(
        self, method: str, *, predicate: Any = None, timeout: float | None = None
    ) -> dict[str, Any]:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        deferred: list[dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                try:
                    item = self._notifications.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if item.get("method") == method and (predicate is None or predicate(item)):
                    return item
                deferred.append(item)
        finally:
            for item in deferred:
                self._notifications.put(item)
        raise LspError(f"Timed out waiting for LSP notification: {method}")

    def collect_notifications(
        self,
        method: str,
        *,
        timeout: float,
        quiet_period: float = 0.15,
    ) -> list[dict[str, Any]]:
        """Collect matching notifications within one bounded workspace window."""
        deadline = time.monotonic() + timeout
        matched: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                wait = min(quiet_period if matched else timeout, deadline - time.monotonic())
                try:
                    item = self._notifications.get(timeout=max(0.01, wait))
                except queue.Empty:
                    if matched:
                        break
                    continue
                if item.get("method") == method:
                    matched.append(item)
                else:
                    deferred.append(item)
        finally:
            for item in deferred:
                self._notifications.put(item)
        return matched

    def supports(self, capability: str) -> bool:
        value = self.capabilities.get(capability)
        return bool(value)

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def stop(self) -> None:
        process = self.process
        if not process:
            return
        try:
            if process.poll() is None:
                try:
                    self.request("shutdown", {})
                    self.notify("exit", {})
                    process.wait(timeout=2)
                except (LspError, subprocess.TimeoutExpired):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
            if self._reader and self._reader is not threading.current_thread():
                self._reader.join(timeout=1)
            if self._stderr_reader and self._stderr_reader is not threading.current_thread():
                self._stderr_reader.join(timeout=1)
            self.process = None
            self._reader = None
            self._stderr_reader = None
            self.capabilities = {}
            self._documents.clear()

    def __enter__(self) -> LspClient:
        self.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.stop()

    def _ensure_running(self) -> None:
        if not self.process or self.process.poll() is not None:
            detail_text = self._reader_error or "\n".join(self._stderr_lines)
            detail = f": {detail_text}" if detail_text else ""
            raise LspError(f"LSP process is not running{detail}")

    def _send(self, payload: dict[str, Any]) -> None:
        process = self.process
        if not process or not process.stdin:
            raise LspError("LSP process stdin is unavailable")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        frame = f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        with self._write_lock:
            try:
                process.stdin.write(frame)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise LspError(f"LSP process closed its input: {exc}") from exc

    def _read_loop(self) -> None:
        process = self.process
        if not process or not process.stdout:
            return
        try:
            while process.poll() is None:
                headers: dict[str, str] = {}
                while True:
                    line = process.stdout.readline()
                    if not line:
                        return
                    if line in {b"\r\n", b"\n"}:
                        break
                    key, _, value = line.decode("ascii", errors="replace").partition(":")
                    headers[key.strip().lower()] = value.strip()
                length = int(headers.get("content-length", "0"))
                if length <= 0:
                    continue
                body = process.stdout.read(length)
                message = json.loads(body.decode("utf-8"))
                response_id = message.get("id")
                if response_id is not None and "method" not in message:
                    pending = self._pending.get(int(response_id))
                    if pending:
                        pending.put(message)
                elif response_id is not None and "method" in message:
                    self._reply_to_server_request(message)
                elif "method" in message:
                    self._notifications.put(message)
        except Exception as exc:
            self._reader_error = f"{type(exc).__name__}: {exc}"

    def _read_stderr(self) -> None:
        """Drain server diagnostics so a full stderr pipe cannot stall the protocol."""
        process = self.process
        if not process or not process.stderr:
            return
        for raw_line in iter(process.stderr.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                self._stderr_lines.append(line)

    def _reply_to_server_request(self, message: dict[str, Any]) -> None:
        """Answer the small set of client requests commonly sent during startup."""
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        if method == "workspace/configuration":
            result: Any = [None for _item in params.get("items", [])]
        elif method == "workspace/workspaceFolders":
            result = [{"uri": self.root.as_uri(), "name": self.root.name}]
        elif method in {
            "client/registerCapability",
            "client/unregisterCapability",
            "window/workDoneProgress/create",
        }:
            result = None
        else:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": f"Unsupported client method: {method}"},
                }
            )
            return
        self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})
