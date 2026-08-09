"""Minimal dual-era JSON-lines MCP peer for interoperability smoke tests.

This intentionally does not import the Python SDK. A conformance fixture should not
share protocol implementation code with the client it is checking.
"""

from __future__ import annotations

import json
import sys
from typing import Any

TOOLS = [
    {
        "name": "echo",
        "description": "Return the provided message.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "choose",
        "description": "Request an explicit user choice.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]
PROMPTS = [
    {
        "name": "review",
        "description": "Review a named file.",
        "arguments": [{"name": "path", "description": "File path", "required": True}],
    }
]
RESOURCES = [
    {
        "uri": "memory://project",
        "name": "Project memory",
        "description": "A compact project note.",
        "mimeType": "text/markdown",
    }
]
RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "memory://item/{name}",
        "name": "Memory item",
        "description": "Read one named memory item.",
        "mimeType": "text/markdown",
    }
]


def _cached(result: dict[str, Any], ttl_ms: int = 60_000) -> dict[str, Any]:
    return {
        **result,
        "ttlMs": ttl_ms,
        "cacheScope": "private",
        "resultType": "complete",
    }


def _reply(request_id: Any, result: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request.get("method")
        print(f"wire fixture received {method}", file=sys.stderr, flush=True)
        if method == "initialize":
            _reply(
                request["id"],
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                    "serverInfo": {"name": "magent-wire-fixture", "version": "1"},
                },
            )
        elif method == "server/discover":
            _reply(
                request["id"],
                {
                    "supportedVersions": ["2026-07-28"],
                    "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                    "resultType": "complete",
                },
            )
        elif method == "tools/list":
            _reply(
                request["id"],
                _cached({"tools": TOOLS}),
            )
        elif method == "prompts/list":
            _reply(request["id"], _cached({"prompts": PROMPTS}))
        elif method == "prompts/get":
            path = (request.get("params") or {}).get("arguments", {}).get("path", "unknown")
            _reply(
                request["id"],
                _cached(
                    {
                        "description": "Generated review prompt",
                        "messages": [
                            {
                                "role": "user",
                                "content": {"type": "text", "text": f"Review {path}"},
                            }
                        ],
                    }
                ),
            )
        elif method == "resources/list":
            _reply(request["id"], _cached({"resources": RESOURCES}))
        elif method == "resources/templates/list":
            _reply(
                request["id"],
                _cached({"resourceTemplates": RESOURCE_TEMPLATES}),
            )
        elif method == "resources/read":
            uri = (request.get("params") or {}).get("uri", "")
            _reply(
                request["id"],
                _cached(
                    {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "text/markdown",
                                "text": "# Project\n\nBridge resource content.",
                            }
                        ]
                    }
                ),
            )
        elif method == "completion/complete":
            value = (request.get("params") or {}).get("argument", {}).get("value", "")
            _reply(
                request["id"],
                {
                    "completion": {
                        "values": [f"{value}.py"],
                        "total": 1,
                        "hasMore": False,
                    },
                    "resultType": "complete",
                },
            )
        elif method == "tools/call":
            params = request.get("params") or {}
            if params.get("name") == "choose" and not params.get("inputResponses"):
                _reply(
                    request["id"],
                    {
                        "resultType": "input_required",
                        "requestState": "sealed-choice-state",
                        "inputRequests": {
                            "choice": {
                                "method": "elicitation/create",
                                "params": {
                                    "message": "Choose a release channel",
                                    "requestedSchema": {
                                        "type": "object",
                                        "properties": {
                                            "channel": {
                                                "type": "string",
                                                "enum": ["stable", "preview"],
                                            }
                                        },
                                        "required": ["channel"],
                                    },
                                },
                            }
                        },
                    },
                )
                continue
            if params.get("name") == "choose":
                answer = params.get("inputResponses", {}).get("choice", {}).get("content", {})
                message = answer.get("channel", "unknown")
            else:
                message = params.get("arguments", {}).get("message", "")
            _reply(
                request["id"],
                {
                    "content": [{"type": "text", "text": message}],
                    "structuredContent": {"message": message},
                    "isError": False,
                    "resultType": "complete",
                },
            )
        else:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request["id"],
                        "error": {"code": -32601, "message": f"unknown method {method}"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()
