"""Private JSON-lines bridge to the MCP Python SDK v2.

The SDK client and transport context must stay in the coroutine that entered them.
Keeping that lifecycle in this small child process avoids event-loop ownership issues
in interactive sessions while isolating protocol failures from the agent runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
from contextlib import AsyncExitStack, suppress
from datetime import UTC, datetime
from typing import Any

_MAX_RESOURCE_CHARS = 200_000

# Environment variables a subprocess needs to start at all. Anything else must
# be named explicitly in the server's `env` block.
_INHERITED_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMDATA",
        "NODE_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    }
)


def _dump(value: Any) -> Any:
    """Convert SDK/Pydantic values into JSON-safe protocol payloads."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":"), default=str) + "\n")
    sys.stdout.flush()


def _error_text(exc: BaseException) -> str:
    """Flatten exception groups into a bounded diagnostic suitable for the parent."""
    nested = getattr(exc, "exceptions", None)
    if nested:
        details = "; ".join(_error_text(item) for item in nested[:3])
        return f"{type(exc).__name__}: {details}"[:2000]
    return f"{type(exc).__name__}: {exc}"[:2000]


class _InputPump:
    """Move buffered stdin lines onto the root event loop from one reader thread."""

    def __init__(self) -> None:
        self._lines: queue.SimpleQueue[str | None] = queue.SimpleQueue()
        threading.Thread(target=self._pump, name="magent-mcp-stdin", daemon=True).start()

    def _pump(self) -> None:
        buffer = b""
        try:
            while chunk := os.read(sys.stdin.fileno(), 4096):
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    self._lines.put(raw.decode("utf-8", errors="replace"))
            if buffer:
                self._lines.put(buffer.decode("utf-8", errors="replace"))
        finally:
            self._lines.put(None)

    async def read(self) -> dict[str, Any] | None:
        while True:
            try:
                line = self._lines.get_nowait()
                break
            except queue.Empty:
                await asyncio.sleep(0.01)
        if line is None:
            return None
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("bridge request must be a JSON object")
        return value


async def _read(source: _InputPump) -> dict[str, Any] | None:
    line = await source.read()
    if not line:
        return None
    return line


def _mode(value: str) -> str:
    return {"modern": "2026-07-28", "legacy": "legacy"}.get(value, "auto")


def _expand_mapping(value: Any) -> dict[str, str] | None:
    """Expand environment references only inside the secret-bearing bridge process."""
    if not isinstance(value, dict):
        return None
    return {str(key): os.path.expandvars(str(item)) for key, item in value.items()}


async def _transport(profile: dict[str, Any], stack: AsyncExitStack) -> Any:
    transport = str(profile.get("transport", "stdio"))
    if transport == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        overrides = _expand_mapping(profile.get("env")) or {}
        # Only pass through what a subprocess genuinely needs plus the explicit
        # overrides. Merging the whole parent environment handed every API key
        # MagAgent holds to any stdio server that declared a single env var.
        env = None
        if overrides:
            inherited = {
                name: value
                for name, value in os.environ.items()
                if name in _INHERITED_ENV_VARS
            }
            env = {**inherited, **overrides}
        params = StdioServerParameters(
            command=str(profile.get("command", "")),
            args=list(profile.get("args") or []),
            env=env,
            cwd=profile.get("cwd") or None,
        )
        return stdio_client(params)

    if transport == "streamable-http":
        # httpx2, not httpx: the MCP SDK depends on httpx2 and
        # streamable_http_client requires an httpx2.AsyncClient specifically.
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        http = await stack.enter_async_context(
            httpx2.AsyncClient(
                headers=_expand_mapping(profile.get("headers")),
                timeout=float(profile.get("timeout", 30.0)),
                follow_redirects=True,
            )
        )
        return streamable_http_client(str(profile.get("url", "")), http_client=http)

    if transport == "legacy-sse":
        from mcp.client.sse import sse_client

        return sse_client(
            str(profile.get("url", "")),
            headers=_expand_mapping(profile.get("headers")),
            timeout=float(profile.get("timeout", 30.0)),
        )
    raise ValueError(f"unsupported MCP transport: {transport}")


def _tool_catalog(result: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in result.tools:
        item = {
            "name": str(tool.name),
            "description": str(tool.description or ""),
            "input_schema": _dump(
                getattr(tool, "input_schema", getattr(tool, "inputSchema", {}))
            ),
            "output_schema": _dump(
                getattr(tool, "output_schema", getattr(tool, "outputSchema", None))
            ),
            "annotations": _dump(getattr(tool, "annotations", None)),
            "meta": _dump(getattr(tool, "meta", None)),
        }
        tools.append({key: value for key, value in item.items() if value is not None})
    return tools


def _catalog_meta(result: Any) -> dict[str, Any]:
    return {
        "fetched_at": datetime.now(UTC).isoformat(),
        "ttl_ms": int(getattr(result, "ttl_ms", getattr(result, "ttlMs", 0)) or 0),
        "cache_scope": str(
            getattr(result, "cache_scope", getattr(result, "cacheScope", "private"))
            or "private"
        ),
        "next_cursor": getattr(result, "next_cursor", getattr(result, "nextCursor", None)),
    }


def _bounded_resource_result(result: Any) -> dict[str, Any]:
    payload = _dump(result)
    if not isinstance(payload, dict):
        return {"contents": [], "truncated": False}
    truncated = False
    contents = payload.get("contents") or []
    for item in contents:
        if not isinstance(item, dict):
            continue
        for key in ("text", "blob"):
            value = item.get(key)
            if isinstance(value, str) and len(value) > _MAX_RESOURCE_CHARS:
                item[key] = value[:_MAX_RESOURCE_CHARS]
                truncated = True
    payload["truncated"] = truncated
    return payload


async def _serve(profile: dict[str, Any], source: _InputPump) -> None:
    from mcp import Client
    from mcp_types import (
        CreateMessageResult,
        CreateMessageResultWithTools,
        ElicitResult,
        ErrorData,
        ListRootsResult,
    )

    timeout = float(profile.get("timeout", 30.0))
    input_sequence = 0

    async def request_host_input(kind: str, payload: Any) -> dict[str, Any]:
        """Ask the parent host for explicit input without writing answers to logs."""
        nonlocal input_sequence
        input_sequence += 1
        token = f"input-{input_sequence}"
        _write(
            {
                "ok": True,
                "event": "input_request",
                "token": token,
                "kind": kind,
                "payload": _dump(payload),
            }
        )
        response = await asyncio.wait_for(_read(source), timeout=timeout * 10)
        if not response or response.get("op") != "input_response" or response.get("token") != token:
            return {"error": "MCP host input was unavailable or mismatched"}
        result = response.get("result")
        return result if isinstance(result, dict) else {"error": "MCP host returned invalid input"}

    async def handle_elicitation(_context: Any, params: Any) -> Any:
        response = await request_host_input("elicitation", params)
        if response.get("error"):
            return ErrorData(code=-32600, message=str(response["error"]))
        return ElicitResult.model_validate(response)

    async def handle_sampling(_context: Any, params: Any) -> Any:
        response = await request_host_input("sampling", params)
        if response.get("error"):
            return ErrorData(code=-32600, message=str(response["error"]))
        try:
            return CreateMessageResult.model_validate(response)
        except Exception:
            return CreateMessageResultWithTools.model_validate(response)

    async def handle_roots(_context: Any) -> Any:
        response = await request_host_input("roots", {})
        if response.get("error"):
            return ErrorData(code=-32600, message=str(response["error"]))
        return ListRootsResult.model_validate(response)

    async def forward_legacy_message(message: Any) -> None:
        """Forward classic notifications without interpreting untrusted payloads."""
        _write({"ok": True, "event": "notification", "payload": _dump(message)})

    async with AsyncExitStack() as stack:
        connector = await _transport(profile, stack)
        client = await stack.enter_async_context(
            Client(
                connector,
                mode=_mode(str(profile.get("protocol_mode", "auto"))),
                message_handler=forward_legacy_message,
                elicitation_callback=handle_elicitation,
                sampling_callback=handle_sampling,
                list_roots_callback=handle_roots,
            )
        )
        tools = await asyncio.wait_for(client.list_tools(), timeout=timeout)
        _write(
            {
                "ok": True,
                "event": "ready",
                "protocol_version": str(client.protocol_version or ""),
                "selected_era": (
                    "modern" if str(client.protocol_version or "").startswith("2026-") else "legacy"
                ),
                "capabilities": _dump(client.server_capabilities),
                "server_info": _dump(client.server_info),
                "instructions": str(client.instructions or ""),
                "tools": _tool_catalog(tools),
                "tools_meta": _catalog_meta(tools),
            }
        )

        subscription_task: asyncio.Task[None] | None = None

        async def forward_modern_subscriptions() -> None:
            try:
                async with client.listen(
                    tools_list_changed=True,
                    prompts_list_changed=True,
                    resources_list_changed=True,
                ) as subscription:
                    _write(
                        {
                            "ok": True,
                            "event": "subscription_status",
                            "status": "active",
                            "honored": _dump(subscription.honored),
                        }
                    )
                    async for event in subscription:
                        _write(
                            {
                                "ok": True,
                                "event": "subscription_event",
                                "payload": _dump(event),
                            }
                        )
                _write(
                    {
                        "ok": True,
                        "event": "subscription_status",
                        "status": "closed",
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _write(
                    {
                        "ok": False,
                        "event": "subscription_status",
                        "status": "unavailable",
                        "error": _error_text(exc),
                    }
                )

        if str(client.protocol_version or "").startswith("2026-"):
            subscription_task = asyncio.create_task(forward_modern_subscriptions())

        try:
            while request := await _read(source):
                request_id = request.get("id")
                try:
                    operation = request.get("op")
                    if operation == "stop":
                        _write({"ok": True, "id": request_id})
                        return
                    if operation == "list_tools":
                        result = await asyncio.wait_for(
                            client.list_tools(
                                cache_mode="refresh" if request.get("refresh") else "use"
                            ),
                            timeout=timeout,
                        )
                        _write(
                            {
                                "ok": True,
                                "id": request_id,
                                "tools": _tool_catalog(result),
                                "meta": _catalog_meta(result),
                            }
                        )
                        continue
                    if operation == "list_prompts":
                        result = await asyncio.wait_for(
                            client.list_prompts(
                                cache_mode="refresh" if request.get("refresh") else "use"
                            ),
                            timeout=timeout,
                        )
                        _write(
                            {
                                "ok": True,
                                "id": request_id,
                                "prompts": _dump(result.prompts),
                                "meta": _catalog_meta(result),
                            }
                        )
                        continue
                    if operation == "get_prompt":
                        result = await asyncio.wait_for(
                            client.get_prompt(
                                str(request.get("name", "")),
                                dict(request.get("arguments") or {}),
                            ),
                            timeout=timeout,
                        )
                        _write({"ok": True, "id": request_id, "result": _dump(result)})
                        continue
                    if operation == "complete":
                        from mcp_types import PromptReference, ResourceTemplateReference

                        reference_type = str(request.get("reference_type") or "prompt")
                        if reference_type == "resource":
                            reference = ResourceTemplateReference(
                                uri=str(request.get("reference", ""))
                            )
                        else:
                            reference = PromptReference(name=str(request.get("reference", "")))
                        result = await asyncio.wait_for(
                            client.complete(
                                reference,
                                dict(request.get("argument") or {}),
                                dict(request.get("context_arguments") or {}),
                            ),
                            timeout=timeout,
                        )
                        _write({"ok": True, "id": request_id, "result": _dump(result)})
                        continue
                    if operation == "list_resources":
                        result = await asyncio.wait_for(
                            client.list_resources(
                                cache_mode="refresh" if request.get("refresh") else "use"
                            ),
                            timeout=timeout,
                        )
                        _write(
                            {
                                "ok": True,
                                "id": request_id,
                                "resources": _dump(result.resources),
                                "meta": _catalog_meta(result),
                            }
                        )
                        continue
                    if operation == "list_resource_templates":
                        result = await asyncio.wait_for(
                            client.list_resource_templates(
                                cache_mode="refresh" if request.get("refresh") else "use"
                            ),
                            timeout=timeout,
                        )
                        _write(
                            {
                                "ok": True,
                                "id": request_id,
                                "resource_templates": _dump(result.resource_templates),
                                "meta": _catalog_meta(result),
                            }
                        )
                        continue
                    if operation == "read_resource":
                        result = await asyncio.wait_for(
                            client.read_resource(
                                str(request.get("uri", "")),
                                cache_mode="refresh" if request.get("refresh") else "use",
                            ),
                            timeout=timeout,
                        )
                        _write(
                            {
                                "ok": True,
                                "id": request_id,
                                "result": _bounded_resource_result(result),
                                "meta": _catalog_meta(result),
                            }
                        )
                        continue
                    if operation == "call_tool":
                        result = await asyncio.wait_for(
                            client.call_tool(
                                str(request.get("name", "")),
                                dict(request.get("arguments") or {}),
                                read_timeout_seconds=timeout,
                            ),
                            timeout=timeout,
                        )
                        _write(
                            {
                                "ok": True,
                                "id": request_id,
                                "result": {
                                    "content": _dump(result.content),
                                    "structured_content": _dump(
                                        getattr(result, "structured_content", None)
                                    ),
                                    "is_error": bool(
                                        getattr(
                                            result,
                                            "is_error",
                                            getattr(result, "isError", False),
                                        )
                                    ),
                                    "meta": _dump(getattr(result, "meta", None)),
                                },
                            }
                        )
                        continue
                    raise ValueError(f"unknown bridge operation: {operation}")
                except Exception as exc:
                    _write({"ok": False, "id": request_id, "error": _error_text(exc)})
        finally:
            if subscription_task:
                subscription_task.cancel()
                with suppress(asyncio.CancelledError):
                    await subscription_task


async def main() -> None:
    """Read a secret-bearing profile from stdin, then serve bridge requests."""
    try:
        source = _InputPump()
        profile = await _read(source)
        if profile is None:
            raise ValueError("missing MCP bridge profile")
        await _serve(profile, source)
    except Exception as exc:
        _write({"ok": False, "event": "fatal", "error": _error_text(exc)})


if __name__ == "__main__":
    asyncio.run(main())
