"""Graph task nodes executed by an MCP tool or an A2A agent (experimental).

AGS 1.0 lets every object carry ``x-`` extension keys that harnesses must
preserve and may honour. MagAgent honours ``x-magagent-executor`` on task nodes:
instead of running a MagAgent model session, the node calls an external
executor and stores its text reply in a declared output.

MCP tool::

    x-magagent-executor:
      kind: mcp
      server: github            # a server under [mcp.servers] in config.toml
      tool: search_issues
      arguments: {query: "${{ inputs.topic }}"}
      output: issues            # a declared node output (default: the first one)

A2A agent (JSON-RPC ``message/send``, polling ``tasks/get`` until the task ends)::

    x-magagent-executor:
      kind: a2a
      url: https://agents.example.com/research   # the agent's JSON-RPC endpoint
      message: "Summarise ${{ inputs.topic }}"   # default: the node's own prompt
      token_env: RESEARCH_AGENT_TOKEN            # optional bearer token variable
      timeout_seconds: 300
      output: summary

Every call is an external side effect, so it asks for approval through the
graph's permission prompt (``--approval-stdio``, the Web UI, the terminal), or
needs ``--yes``. HTTPS is required for A2A except on loopback.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

EXECUTOR_KEY = "x-magagent-executor"
A2A_TERMINAL = {"completed", "failed", "canceled", "rejected"}
A2A_BLOCKED = {"input-required", "auth-required"}
MAX_REPLY_CHARS = 200_000

Approve = Callable[[dict[str, Any], str], Awaitable[bool]]


class ExecutorError(RuntimeError):
    def __init__(self, message: str, code: str = "RT040") -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def executor_for(node: dict[str, Any]) -> dict[str, Any] | None:
    value = node.get(EXECUTOR_KEY)
    return value if isinstance(value, dict) else None


def validate_executor(node_id: str, node: dict[str, Any]) -> list[str]:
    """Human-readable problems with a node's executor block (empty = fine)."""

    executor = executor_for(node)
    if executor is None:
        return [] if EXECUTOR_KEY not in node else [f"{node_id}: {EXECUTOR_KEY} must be a mapping"]
    problems: list[str] = []
    if node.get("type") != "task":
        problems.append(f"{node_id}: {EXECUTOR_KEY} is only supported on task nodes")
    kind = executor.get("kind")
    if kind == "mcp":
        for key in ("server", "tool"):
            if not str(executor.get(key) or "").strip():
                problems.append(f"{node_id}: mcp executor needs '{key}'")
        if not isinstance(executor.get("arguments", {}), dict):
            problems.append(f"{node_id}: mcp executor 'arguments' must be a mapping")
    elif kind == "a2a":
        url = str(executor.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            problems.append(f"{node_id}: a2a executor needs an http(s) 'url'")
        elif parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            problems.append(f"{node_id}: a2a executor must use https except on loopback")
    else:
        problems.append(f"{node_id}: executor kind must be 'mcp' or 'a2a'")
    outputs = node.get("outputs") or {}
    output = executor.get("output")
    if output is not None and output not in outputs:
        problems.append(f"{node_id}: executor output {output!r} is not a declared node output")
    if not outputs:
        problems.append(f"{node_id}: a node with an executor must declare an output")
    return problems


def _output_name(node: dict[str, Any], executor: dict[str, Any]) -> str:
    return str(executor.get("output") or next(iter(node.get("outputs") or {"result": {}})))


async def run_executor(
    node_id: str,
    node: dict[str, Any],
    *,
    prompt: str,
    scope: dict[str, Any],
    mcp_servers: dict[str, Any],
    approve: Approve,
) -> dict[str, Any]:
    """Run the node's executor and return {output_name: value, plus bookkeeping}."""

    from magent.agraph.expressions import resolve_value

    executor = executor_for(node) or {}
    problems = validate_executor(node_id, node)
    if problems:
        raise ExecutorError("; ".join(problems), "RT041")
    kind = executor["kind"]
    started = time.monotonic()
    if kind == "mcp":
        server = str(executor["server"])
        tool = str(executor["tool"])
        arguments = resolve_value(executor.get("arguments") or {}, scope)
        action = {
            "kind": "tool.call",
            "name": f"mcp.{server}.{tool}",
            "summary": f"Call MCP tool {tool} on server {server} for graph node {node_id}",
            "arguments": arguments,
            "effects": [f"Runs the {tool} tool of the {server} MCP server."],
        }
        if not await approve(action, f"Graph node {node_id} calls MCP {server}.{tool}"):
            raise ExecutorError(f"the MCP call for {node_id} was not approved", "RT042")
        reply = await _call_mcp(server, tool, arguments, mcp_servers)
    else:
        url = str(executor["url"])
        message = str(resolve_value(executor.get("message") or prompt, scope))
        action = {
            "kind": "agent.message",
            "name": "a2a.message/send",
            "summary": f"Send graph node {node_id}'s task to the A2A agent at {url}",
            "arguments": {"url": url, "message": message},
            "effects": ["Sends the task text to an external agent over the network."],
        }
        if not await approve(action, f"Graph node {node_id} messages A2A agent {url}"):
            raise ExecutorError(f"the A2A call for {node_id} was not approved", "RT042")
        token_env = str(executor.get("token_env") or "")
        reply = await _call_a2a(
            url,
            message,
            token=os.environ.get(token_env, "") if token_env else "",
            timeout=float(executor.get("timeout_seconds") or 300),
        )
    reply = reply[:MAX_REPLY_CHARS]
    value: Any = reply
    if executor.get("json"):
        try:
            value = json.loads(reply)
        except ValueError as error:
            raise ExecutorError(
                f"{node_id}: executor reply is not JSON ({error})", "RT043"
            ) from error
    return {
        _output_name(node, executor): value,
        "_magent_summary": f"{kind} executor finished in {time.monotonic() - started:.1f}s",
        "_magent_files_changed": [],
    }


async def _call_mcp(
    server: str, tool: str, arguments: dict[str, Any], mcp_servers: dict[str, Any]
) -> str:
    from magent.mcp.manager import MCPManager

    config = mcp_servers.get(server)
    if not isinstance(config, dict):
        raise ExecutorError(
            f"MCP server {server!r} is not configured; add it under [mcp.servers] "
            "(see `magent mcp init`)",
            "RT044",
        )
    manager = MCPManager({server: config})
    try:
        await manager.start_all()
        result = await manager.call(server, tool, arguments)
    finally:
        await manager.stop_all()
    if not result.get("ok"):
        raise ExecutorError(f"MCP {server}.{tool} failed: {result.get('error')}", "RT045")
    return str(result.get("result") or "")


def _a2a_text(result: dict[str, Any]) -> str:
    """Text from an A2A Message or Task result (artifacts first, then the status message)."""

    def parts_text(parts: Any) -> list[str]:
        return [
            str(part.get("text"))
            for part in parts or []
            if isinstance(part, dict) and part.get("kind", part.get("type")) == "text"
        ]

    if result.get("kind") == "message" or "parts" in result:
        return "\n".join(parts_text(result.get("parts")))
    texts: list[str] = []
    for artifact in result.get("artifacts") or []:
        if isinstance(artifact, dict):
            texts.extend(parts_text(artifact.get("parts")))
    if not texts:
        message = (result.get("status") or {}).get("message") or {}
        texts.extend(parts_text(message.get("parts")))
    return "\n".join(texts)


async def _call_a2a(url: str, message: str, *, token: str, timeout: float) -> str:
    import httpx

    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    deadline = time.monotonic() + timeout

    async def rpc(client: httpx.AsyncClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await client.post(
            url,
            json={"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": params},
            headers=headers,
        )
        if response.status_code >= 400:
            raise ExecutorError(f"A2A agent returned HTTP {response.status_code}", "RT046")
        payload = response.json()
        if payload.get("error"):
            raise ExecutorError(
                f"A2A agent error: {payload['error'].get('message', payload['error'])}", "RT046"
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ExecutorError("A2A agent returned no result", "RT046")
        return result

    async with httpx.AsyncClient(timeout=min(60.0, timeout), follow_redirects=False) as client:
        result = await rpc(
            client,
            "message/send",
            {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "messageId": uuid.uuid4().hex,
                    "parts": [{"kind": "text", "text": message}],
                },
                "configuration": {"blocking": True, "acceptedOutputModes": ["text/plain"]},
            },
        )
        while result.get("kind") == "task" or "status" in result:
            state = str((result.get("status") or {}).get("state") or "")
            if state in A2A_TERMINAL:
                if state != "completed":
                    raise ExecutorError(
                        f"A2A task ended {state}: {_a2a_text(result)[:300]}", "RT047"
                    )
                break
            if state in A2A_BLOCKED:
                raise ExecutorError(
                    f"A2A task needs {state.replace('-', ' ')}; graphs cannot answer it", "RT047"
                )
            if time.monotonic() >= deadline:
                raise ExecutorError("A2A task did not finish in time", "RT048")
            await asyncio.sleep(1.0)
            result = await rpc(client, "tasks/get", {"id": result.get("id")})
    return _a2a_text(result)
