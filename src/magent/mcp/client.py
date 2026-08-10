"""MCP client adapter backed by a lifecycle-isolated SDK v2 bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from magent.mcp.catalog import MCPCatalogFreshness, MCPPrompt, MCPResource
from magent.mcp.profile import MCPProtocolMode, MCPServerProfile, MCPTransport

# The bridge may send a whole resource on one line; the asyncio default is 64 KiB.
MAX_BRIDGE_LINE_BYTES = 4 * 1024 * 1024

log = logging.getLogger("magent.mcp.client")

MCPInputHandler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass
class MCPTool:
    """A tool exposed by an MCP server, adapted for MagAgent."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str
    output_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    qualified_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.qualified_name = f"mcp__{self.server_name}__{self.name}"

    def to_openai_definition(self) -> dict[str, Any]:
        schema = self.input_schema if self.input_schema is not None else {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": f"[{self.server_name}] {self.description}",
                "parameters": schema,
            },
        }


class MCPClient:
    """Manage one dual-era MCP connection through a private child process."""

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = 30.0,
        protocol_mode: MCPProtocolMode | str = MCPProtocolMode.AUTO,
        transport: MCPTransport | str = MCPTransport.STDIO,
        url: str = "",
        headers: dict[str, str] | None = None,
        input_handler: MCPInputHandler | None = None,
    ):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.timeout = timeout
        self.protocol_mode = MCPProtocolMode(protocol_mode)
        self.transport = MCPTransport(transport)
        self.url = url
        self.headers = headers
        self.input_handler = input_handler
        self._process: asyncio.subprocess.Process | None = None
        self._session: Any = None  # Compatibility seam for small in-process test doubles.
        self._request_lock = asyncio.Lock()
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: list[str] = []
        self._next_request_id = 0
        self._tools: list[MCPTool] = []
        self._prompts: list[MCPPrompt] = []
        self._resources: list[MCPResource] = []
        self._resource_templates: list[MCPResource] = []
        self._catalog_freshness: dict[str, MCPCatalogFreshness] = {}
        self._resource_reads_stale = False
        self.catalog_errors: dict[str, str] = {}
        self._connected = False
        self.selected_era = ""
        self.selected_protocol_version = ""
        self.capabilities: dict[str, Any] = {}
        self.server_info: dict[str, Any] = {}
        self.instructions = ""
        self.subscription: dict[str, Any] = {
            "status": "not_started",
            "honored": {},
            "events": 0,
            "last_event": "",
            "error": "",
        }
        self.last_error = ""
        self._secret_values = _secret_values(env, headers)

    @classmethod
    def from_profile(cls, profile: MCPServerProfile) -> MCPClient:
        return cls(
            server_name=profile.name,
            command=profile.command,
            args=list(profile.args),
            env=profile.env,
            cwd=profile.cwd,
            timeout=profile.timeout,
            protocol_mode=profile.protocol_mode,
            transport=profile.transport,
            url=profile.url,
            headers=profile.headers,
        )

    def _profile_payload(self) -> dict[str, Any]:
        return {
            "transport": self.transport.value,
            "protocol_mode": self.protocol_mode.value,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
            "url": self.url,
            "headers": self.headers,
            "timeout": self.timeout,
        }

    async def connect(self) -> bool:
        """Start the private SDK bridge, negotiate an era, and discover tools."""
        self.last_error = ""
        try:
            self._process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(Path(__file__).with_name("bridge.py")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # The default StreamReader limit is 64 KiB, but the bridge will
                # happily send a 200,000-character resource; without this a
                # large tool result raised LimitOverrunError.
                limit=MAX_BRIDGE_LINE_BYTES,
            )
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            await self._send_line(self._profile_payload())
            ready = await self._read_line(timeout=self.timeout * 2)
            if not ready.get("ok") or ready.get("event") != "ready":
                raise RuntimeError(
                    self._redact(str(ready.get("error") or "MCP bridge did not become ready"))
                )
            self.selected_era = str(ready.get("selected_era") or "")
            self.selected_protocol_version = str(ready.get("protocol_version") or "")
            self.capabilities = _as_dict(ready.get("capabilities"))
            self.server_info = _as_dict(ready.get("server_info"))
            self.instructions = str(ready.get("instructions") or "")
            self._set_tools(ready.get("tools"))
            self._set_catalog_meta("tools", ready.get("tools_meta"))
            self._connected = True
            log.info("MCP [%s] connected - %d tools available", self.server_name, len(self._tools))
            return True
        except TimeoutError:
            self.last_error = f"MCP [{self.server_name}] connection timed out"
        except Exception as exc:
            self.last_error = f"MCP [{self.server_name}] connect failed: {exc}"
        if self._stderr_tail:
            log.debug("MCP [%s] bridge stderr: %s", self.server_name, " | ".join(self._stderr_tail))
        log.error(self.last_error)
        await self.disconnect()
        return False

    async def disconnect(self) -> None:
        """Stop the bridge and its server transport without leaking child processes."""
        process = self._process
        if process and process.returncode is None:
            with suppress(Exception):
                await self._request("stop", timeout=min(self.timeout, 2.0))
            if process.stdin:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.terminate()
                with suppress(Exception):
                    await asyncio.wait_for(process.wait(), timeout=2.0)
        if self._stderr_task:
            self._stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stderr_task
        self._process = None
        self._session = None
        self._stderr_task = None
        self._connected = False
        self.selected_era = ""
        self.selected_protocol_version = ""
        self.capabilities = {}
        self.server_info = {}
        self.instructions = ""

    @property
    def connected(self) -> bool:
        return self._connected

    def public_status(self) -> dict[str, Any]:
        endpoint = self.command + (f" ({len(self.args)} args)" if self.args else "")
        if self.transport is not MCPTransport.STDIO:
            endpoint = MCPServerProfile(
                name=self.server_name,
                transport=self.transport,
                protocol_mode=self.protocol_mode,
                url=self.url,
            ).public_endpoint
        return {
            "name": self.server_name,
            "transport": self.transport.value,
            "protocol_mode": self.protocol_mode.value,
            "selected_era": self.selected_era,
            "protocol_version": self.selected_protocol_version,
            "endpoint": endpoint,
            "connected": self.connected,
            "tools": [tool.name for tool in self.tools],
            "catalogs": self.catalog_status(),
            "capabilities": self.capabilities,
            "instructions_present": bool(self.instructions),
            "subscription": dict(self.subscription),
            "error": self.last_error,
        }

    async def list_tools(self, *, refresh: bool = False) -> list[MCPTool]:
        if self._session is not None:
            try:
                result = await asyncio.wait_for(self._session.list_tools(), timeout=self.timeout)
                self._tools = [
                    MCPTool(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=_tool_input_schema(tool),
                        server_name=self.server_name,
                    )
                    for tool in result.tools
                ]
            except Exception as exc:
                log.error("MCP [%s] list_tools failed: %s", self.server_name, exc)
            return self._tools
        if not self._connected:
            return []
        if not refresh and "tools" in self._catalog_freshness and self._catalog_is_fresh("tools"):
            return self._tools
        response = await self._request(
            "list_tools", refresh=refresh or self._catalog_is_stale("tools")
        )
        if response.get("ok"):
            self._set_tools(response.get("tools"))
            self._set_catalog_meta("tools", response.get("meta"))
            self.catalog_errors.pop("tools", None)
        else:
            self._record_catalog_error("tools", response)
        return self._tools

    @property
    def tools(self) -> list[MCPTool]:
        return self._tools

    def get_tool(self, original_name: str) -> MCPTool | None:
        return next((tool for tool in self._tools if tool.name == original_name), None)

    async def list_prompts(self, *, refresh: bool = False) -> list[MCPPrompt]:
        if not self._connected:
            return []
        if not refresh and "prompts" in self._catalog_freshness and self._catalog_is_fresh("prompts"):
            return self._prompts
        response = await self._request(
            "list_prompts", refresh=refresh or self._catalog_is_stale("prompts")
        )
        if response.get("ok"):
            self._prompts = [
                MCPPrompt.from_payload(item, self.server_name)
                for item in response.get("prompts") or []
                if isinstance(item, dict) and item.get("name")
            ]
            self._prompts.sort(key=lambda item: item.name.casefold())
            self._set_catalog_meta("prompts", response.get("meta"))
            self.catalog_errors.pop("prompts", None)
        else:
            self._record_catalog_error("prompts", response)
        return self._prompts

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> dict[str, Any]:
        if not self._connected:
            return {"ok": False, "error": f"MCP [{self.server_name}] not connected"}
        response = await self._request("get_prompt", name=name, arguments=arguments or {})
        if not response.get("ok"):
            return {"ok": False, "error": self._redact(str(response.get("error") or "Prompt failed"))}
        return {"ok": True, "server": self.server_name, **_as_dict(response.get("result"))}

    async def complete(
        self,
        reference: str,
        argument: dict[str, str],
        *,
        reference_type: str = "prompt",
        context_arguments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Request prompt or resource-template argument completions."""
        if not self._connected:
            return {"ok": False, "error": f"MCP [{self.server_name}] not connected"}
        if reference_type not in {"prompt", "resource"}:
            return {"ok": False, "error": "reference_type must be prompt or resource"}
        response = await self._request(
            "complete",
            reference=reference,
            reference_type=reference_type,
            argument=argument,
            context_arguments=context_arguments or {},
        )
        if not response.get("ok"):
            return {
                "ok": False,
                "error": self._redact(str(response.get("error") or "Completion failed")),
            }
        return {"ok": True, "server": self.server_name, **_as_dict(response.get("result"))}

    async def list_resources(self, *, refresh: bool = False) -> list[MCPResource]:
        if not self._connected:
            return []
        if not refresh and "resources" in self._catalog_freshness and self._catalog_is_fresh("resources"):
            return self._resources
        response = await self._request(
            "list_resources", refresh=refresh or self._catalog_is_stale("resources")
        )
        if response.get("ok"):
            self._resources = [
                MCPResource.from_payload(item, self.server_name)
                for item in response.get("resources") or []
                if isinstance(item, dict) and item.get("uri")
            ]
            self._resources.sort(key=lambda item: (item.name.casefold(), item.uri))
            self._set_catalog_meta("resources", response.get("meta"))
            self.catalog_errors.pop("resources", None)
        else:
            self._record_catalog_error("resources", response)
        return self._resources

    async def list_resource_templates(self, *, refresh: bool = False) -> list[MCPResource]:
        key = "resource_templates"
        if not self._connected:
            return []
        if not refresh and key in self._catalog_freshness and self._catalog_is_fresh(key):
            return self._resource_templates
        response = await self._request(
            "list_resource_templates", refresh=refresh or self._catalog_is_stale(key)
        )
        if response.get("ok"):
            self._resource_templates = [
                MCPResource.from_payload(item, self.server_name, template=True)
                for item in response.get("resource_templates") or []
                if isinstance(item, dict) and item.get("uri_template")
            ]
            self._resource_templates.sort(key=lambda item: (item.name.casefold(), item.uri))
            self._set_catalog_meta(key, response.get("meta"))
            self.catalog_errors.pop(key, None)
        else:
            self._record_catalog_error(key, response)
        return self._resource_templates

    async def read_resource(self, uri: str, *, refresh: bool = False) -> dict[str, Any]:
        if not self._connected:
            return {"ok": False, "error": f"MCP [{self.server_name}] not connected"}
        response = await self._request(
            "read_resource", uri=uri, refresh=refresh or self._resource_reads_stale
        )
        if not response.get("ok"):
            return {
                "ok": False,
                "error": self._redact(str(response.get("error") or "Resource read failed")),
            }
        self._resource_reads_stale = False
        return {
            "ok": True,
            "server": self.server_name,
            **_as_dict(response.get("result")),
            "cache": MCPCatalogFreshness.from_payload(response.get("meta")).public_summary(),
        }

    def invalidate_catalogs(self, reason: str, *catalogs: str) -> None:
        """Mark cached catalogs stale after mutations or subscription events."""
        targets = catalogs or tuple(self._catalog_freshness)
        if not catalogs or "resources" in catalogs or "resource_templates" in catalogs:
            self._resource_reads_stale = True
        for key in targets:
            freshness = self._catalog_freshness.get(key)
            if freshness:
                freshness.invalidate(reason)

    def apply_catalog_event(self, event: str) -> None:
        """Apply one normalized classic or modern subscription event."""
        mapping = {
            "tools/list_changed": ("tools",),
            "prompts/list_changed": ("prompts",),
            "resources/list_changed": ("resources", "resource_templates"),
            "resources/updated": ("resources", "resource_templates"),
        }
        targets = mapping.get(event)
        if targets:
            self.invalidate_catalogs(f"subscription:{event}", *targets)

    def catalog_status(self) -> dict[str, Any]:
        counts = {
            "tools": len(self._tools),
            "prompts": len(self._prompts),
            "resources": len(self._resources),
            "resource_templates": len(self._resource_templates),
        }
        status = {
            key: {
                "count": count,
                "loaded": key in self._catalog_freshness,
                "freshness": (
                    self._catalog_freshness[key].public_summary()
                    if key in self._catalog_freshness
                    else {}
                ),
                "error": self.catalog_errors.get(key, ""),
            }
            for key, count in counts.items()
        }
        status["resources"]["reads_stale"] = self._resource_reads_stale
        return status

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._connected:
            return {"ok": False, "error": f"MCP [{self.server_name}] not connected"}
        if self._session is not None:
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool(tool_name, arguments), timeout=self.timeout
                )
                is_error = bool(getattr(result, "isError", getattr(result, "is_error", False)))
                text = _extract_text(result.content)
                if is_error:
                    return {"ok": False, "error": text, "server": self.server_name}
                return {"ok": True, "result": text, "server": self.server_name}
            except TimeoutError:
                return {"ok": False, "error": f"MCP [{self.server_name}].{tool_name} timed out"}
            except Exception as exc:
                return {"ok": False, "error": f"MCP [{self.server_name}].{tool_name} error: {exc}"}
        try:
            response = await self._request("call_tool", name=tool_name, arguments=arguments)
            self.invalidate_catalogs(f"tool-call:{tool_name}")
            if not response.get("ok"):
                return {
                    "ok": False,
                    "error": self._redact(str(response.get("error") or "MCP tool failed")),
                }
            payload = _as_dict(response.get("result"))
            text = _extract_text(list(payload.get("content") or []))
            if payload.get("is_error"):
                return {"ok": False, "error": text, "server": self.server_name}
            output: dict[str, Any] = {"ok": True, "result": text, "server": self.server_name}
            output["content"] = list(payload.get("content") or [])
            if payload.get("structured_content") is not None:
                output["structured_content"] = payload["structured_content"]
            if payload.get("meta") is not None:
                output["meta"] = payload["meta"]
            return output
        except TimeoutError:
            self.invalidate_catalogs(f"tool-timeout:{tool_name}")
            return {"ok": False, "error": f"MCP [{self.server_name}].{tool_name} timed out"}
        except Exception as exc:
            self.invalidate_catalogs(f"tool-error:{tool_name}")
            return {"ok": False, "error": f"MCP [{self.server_name}].{tool_name} error: {exc}"}

    async def _request(self, operation: str, timeout: float | None = None, **values: Any) -> dict[str, Any]:
        async with self._request_lock:
            self._next_request_id += 1
            request_id = self._next_request_id
            await self._send_line({"id": request_id, "op": operation, **values})
            while True:
                response = await self._read_line(timeout=timeout or self.timeout)
                if response.get("event"):
                    if response.get("event") == "input_request":
                        await self._answer_input_request(response)
                        continue
                    self._apply_bridge_event(response)
                    continue
                response_id = response.get("id")
                if response_id != request_id:
                    # A reply that arrives after its `wait_for` timed out is
                    # stale, not fatal. Raising here left the stream off by one
                    # and failed every subsequent request forever.
                    if isinstance(response_id, int) and response_id < request_id:
                        continue
                    raise RuntimeError("MCP bridge response ID mismatch")
                return response

    async def _send_line(self, value: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("MCP bridge is not running")
        self._process.stdin.write((json.dumps(value, separators=(",", ":")) + "\n").encode())
        await self._process.stdin.drain()

    async def _read_line(self, *, timeout: float) -> dict[str, Any]:
        if not self._process or not self._process.stdout:
            raise RuntimeError("MCP bridge is not running")
        raw = await asyncio.wait_for(self._process.stdout.readline(), timeout=timeout)
        if not raw:
            detail = " | ".join(self._stderr_tail[-3:])
            raise RuntimeError(f"MCP bridge exited unexpectedly{': ' + detail if detail else ''}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            # Server libraries sometimes print to stdout. Skip the noise rather
            # than tearing down the connection.
            self._stderr_tail.append(f"ignored non-JSON bridge line: {raw[:200]!r}")
            return await self._read_line(timeout=timeout)
        if not isinstance(value, dict):
            self._stderr_tail.append(f"ignored non-object bridge line: {raw[:200]!r}")
            return await self._read_line(timeout=timeout)
        return value

    async def _drain_stderr(self) -> None:
        if not self._process or not self._process.stderr:
            return
        while raw := await self._process.stderr.readline():
            line = raw.decode(errors="replace").strip()
            if line:
                self._stderr_tail = [*self._stderr_tail[-19:], self._redact(line[:500])]

    def _redact(self, value: str) -> str:
        for secret in self._secret_values:
            value = value.replace(secret, "[redacted]")
        return value

    def _set_tools(self, values: Any) -> None:
        self._tools = [
            MCPTool(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                input_schema=_as_dict(item.get("input_schema")),
                server_name=self.server_name,
                output_schema=_as_dict(item.get("output_schema")),
                annotations=_as_dict(item.get("annotations")),
                metadata=_as_dict(item.get("meta")),
            )
            for item in (values or [])
            if isinstance(item, dict) and item.get("name")
        ]
        self._tools.sort(key=lambda item: item.name.casefold())

    def _apply_bridge_event(self, message: dict[str, Any]) -> None:
        event = str(message.get("event") or "")
        if event == "subscription_status":
            self.subscription["status"] = str(message.get("status") or "unknown")
            self.subscription["honored"] = _as_dict(message.get("honored"))
            self.subscription["error"] = self._redact(str(message.get("error") or ""))
            return
        if event not in {"subscription_event", "notification"}:
            return
        normalized = _normalized_notification(message.get("payload"))
        if not normalized:
            return
        self.subscription["events"] = int(self.subscription.get("events") or 0) + 1
        self.subscription["last_event"] = normalized
        self.apply_catalog_event(normalized)

    async def _answer_input_request(self, message: dict[str, Any]) -> None:
        result: dict[str, Any]
        if self.input_handler is None:
            result = {
                "error": (
                    "This MCP request needs explicit user input, but the current host "
                    "does not provide an interactive input handler."
                )
            }
        else:
            try:
                candidate = self.input_handler(
                    {
                        "server": self.server_name,
                        "kind": str(message.get("kind") or "unknown"),
                        "payload": _as_dict(message.get("payload")),
                    }
                )
                if isinstance(candidate, Awaitable):
                    candidate = await candidate
                result = candidate if isinstance(candidate, dict) else {"error": "Invalid input response"}
            except Exception as exc:
                result = {"error": f"MCP input handler failed: {exc}"}
        await self._send_line(
            {
                "op": "input_response",
                "token": str(message.get("token") or ""),
                "result": result,
            }
        )

    def _set_catalog_meta(self, key: str, value: Any) -> None:
        self._catalog_freshness[key] = MCPCatalogFreshness.from_payload(value)

    def _catalog_is_fresh(self, key: str) -> bool:
        freshness = self._catalog_freshness.get(key)
        return bool(freshness and freshness.fresh)

    def _catalog_is_stale(self, key: str) -> bool:
        freshness = self._catalog_freshness.get(key)
        return bool(freshness and freshness.stale)

    def _record_catalog_error(self, key: str, response: dict[str, Any]) -> None:
        self.catalog_errors[key] = self._redact(
            str(response.get("error") or f"MCP {key} request failed")
        )


def _extract_text(content_list: list[Any]) -> str:
    """Flatten MCP content items while retaining useful non-text references."""
    parts: list[str] = []
    for item in content_list:
        value = item if isinstance(item, dict) else None
        item_type = value.get("type") if value else getattr(item, "type", None)
        if item_type == "text":
            parts.append(str(value.get("text", "") if value else getattr(item, "text", "")))
        elif item_type in {"image", "audio"}:
            mime = (
                value.get("mime_type", value.get("mimeType", "unknown"))
                if value
                else getattr(item, "mimeType", getattr(item, "mime_type", "unknown"))
            )
            parts.append(f"[{item_type}/{mime}]")
        elif item_type == "resource":
            resource = value.get("resource") if value else getattr(item, "resource", None)
            resource = resource or {}
            uri = resource.get("uri", "?") if isinstance(resource, dict) else getattr(resource, "uri", "?")
            text = resource.get("text") if isinstance(resource, dict) else getattr(resource, "text", None)
            parts.append(f"[resource: {uri}]" + (f"\n{text}" if text else ""))
        elif item_type == "resource_link":
            uri = value.get("uri", "?") if value else getattr(item, "uri", "?")
            parts.append(f"[resource: {uri}]")
        else:
            parts.append(str(item))
    return "\n".join(part for part in parts if part)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(exclude_none=True)
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _tool_input_schema(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", getattr(tool, "input_schema", None))
    return schema if isinstance(schema, dict) else _as_dict(schema)


def _normalized_notification(value: Any) -> str:
    """Find a supported notification method in SDK or wire-shaped payloads."""
    aliases = {
        "notifications/tools/list_changed": "tools/list_changed",
        "tools/list_changed": "tools/list_changed",
        "tools_list_changed": "tools/list_changed",
        "notifications/prompts/list_changed": "prompts/list_changed",
        "prompts/list_changed": "prompts/list_changed",
        "prompts_list_changed": "prompts/list_changed",
        "notifications/resources/list_changed": "resources/list_changed",
        "resources/list_changed": "resources/list_changed",
        "resources_list_changed": "resources/list_changed",
        "notifications/resources/updated": "resources/updated",
        "resources/updated": "resources/updated",
        "resource_updated": "resources/updated",
    }

    def visit(item: Any) -> str:
        if isinstance(item, str):
            lowered = item.strip().lower()
            return aliases.get(lowered, "")
        if isinstance(item, dict):
            for key in ("method", "type", "event"):
                found = visit(item.get(key))
                if found:
                    return found
            for child in item.values():
                found = visit(child)
                if found:
                    return found
        if isinstance(item, list):
            for child in item:
                found = visit(child)
                if found:
                    return found
        return ""

    return visit(value)


def _secret_values(
    env: dict[str, str] | None, headers: dict[str, str] | None
) -> tuple[str, ...]:
    values: set[str] = set()
    for raw in (*((env or {}).values()), *((headers or {}).values())):
        expanded = os.path.expandvars(raw)
        if len(expanded) >= 4:
            values.add(expanded)
        if expanded.lower().startswith("bearer ") and len(expanded) > 11:
            values.add(expanded[7:])
    return tuple(sorted(values, key=len, reverse=True))
