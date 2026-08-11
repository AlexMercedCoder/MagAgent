"""Deterministic JSON-RPC language server used by MagAgent protocol tests."""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
    body = sys.stdin.buffer.read(int(headers["content-length"]))
    return json.loads(body)


def send(payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    sys.stdout.buffer.flush()


def main() -> None:
    open_uri = ""
    while message := read_message():
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            print("fake server ready", file=sys.stderr, flush=True)
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "capabilities": {
                            "workspaceSymbolProvider": True,
                            "definitionProvider": True,
                            "referencesProvider": True,
                            "hoverProvider": True,
                            "renameProvider": True,
                        }
                    },
                }
            )
        elif method == "initialized":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": 9001,
                    "method": "workspace/configuration",
                    "params": {"items": [{"section": "fake"}]},
                }
            )
        elif method == "textDocument/didOpen":
            open_uri = params["textDocument"]["uri"]
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {
                        "uri": open_uri,
                        "diagnostics": [
                            {
                                "range": {
                                    "start": {"line": 0, "character": 0},
                                    "end": {"line": 0, "character": 3},
                                },
                                "severity": 2,
                                "message": "fake warning",
                            }
                        ],
                    },
                }
            )
        elif method == "workspace/symbol":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": [
                        {
                            "name": "demo",
                            "kind": 12,
                            "location": {
                                "uri": open_uri or "file:///tmp/demo.py",
                                "range": {"start": {"line": 0, "character": 4}},
                            },
                        }
                    ],
                }
            )
        elif method in {"textDocument/definition", "textDocument/references"}:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": [
                        {
                            "uri": params["textDocument"]["uri"],
                            "range": {"start": params["position"], "end": params["position"]},
                        }
                    ],
                }
            )
        elif method == "textDocument/hover":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"contents": "demo hover"}})
        elif method == "textDocument/rename":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"changes": {}}})
        elif method == "test/slow":
            time.sleep(1)
            send({"jsonrpc": "2.0", "id": request_id, "result": None})
        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": request_id, "result": None})
        elif method == "exit":
            return


if __name__ == "__main__":
    main()
