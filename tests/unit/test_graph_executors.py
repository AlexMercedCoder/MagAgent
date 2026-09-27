"""Phase 6: AGS task nodes run by an MCP tool or an A2A agent."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from magent.agraph.execute import GraphExecutor
from magent.agraph.validate import validate_graph
from magent.config import DEFAULT_GLOBAL_CONFIG, Config
from magent.workbench_store import WorkbenchStore

ROOT = Path(__file__).resolve().parents[2]
MCP_FIXTURE = ROOT / "tests" / "fixtures" / "mcp_dual_server.py"


def graph(executor: dict) -> dict:
    return {
        "ags_version": "1.0",
        "kind": "AgenticGraph",
        "id": "tests/executor",
        "title": "Executor test",
        "objective": "Run a node through an external executor.",
        "version": "1.0.0",
        "requires_conformance": 1,
        "params": {"topic": {"type": "string", "description": "Topic.", "default": "release"}},
        "entrypoints": ["call"],
        "nodes": {
            "call": {
                "type": "task",
                "title": "Call out",
                "description": "Ask the external executor.",
                "inputs": {
                    "topic": {"type": "string", "description": "Topic.", "from": "params.topic"}
                },
                "outputs": {"answer": {"type": "string", "description": "The reply."}},
                "requirements": {"tools": [], "permissions": []},
                "x-magagent-executor": executor,
                "success": {
                    "summary": "An answer exists.",
                    "criteria": [
                        {
                            "id": "answer",
                            "kind": "artifact_present",
                            "description": "Answer.",
                            "output": "answer",
                        }
                    ],
                },
            }
        },
        "outputs": {
            "answer": {
                "type": "string",
                "description": "Answer.",
                "from": "nodes.call.outputs.answer",
            }
        },
    }


def executor(tmp_path: Path, *, prompt=None, assume_yes=False, mcp=None) -> GraphExecutor:
    raw = json.loads(json.dumps(DEFAULT_GLOBAL_CONFIG))
    raw["mcp"] = {"servers": mcp or {}}

    async def no_model(*_args):  # the executor, not a model, must answer
        raise AssertionError("a model session was started for an executor node")

    return GraphExecutor(
        username="test",
        config=Config(raw),
        project=tmp_path,
        store=WorkbenchStore(tmp_path / "store"),
        agent_runner=no_model,
        permission_prompt=prompt,
        assume_yes=assume_yes,
    )


MCP = {
    "kind": "mcp",
    "server": "fixture",
    "tool": "echo",
    "arguments": {"message": "topic=${{ inputs.topic }}"},
    "output": "answer",
}


def test_mcp_executor_calls_the_tool_after_approval(tmp_path: Path) -> None:
    asked: list[tuple[str, int, dict]] = []

    def prompt(description, tier, action):
        asked.append((description, tier, action))
        return "once"

    runner = executor(
        tmp_path,
        prompt=prompt,
        mcp={"fixture": {"command": sys.executable, "args": [str(MCP_FIXTURE)], "timeout": 10}},
    )
    result = asyncio.run(runner.run(graph(MCP)))
    assert result["ok"], result["run"]["diagnostics"]
    assert "topic=release" in str(result["run"]["outputs"]["answer"])
    [(description, tier, action)] = asked
    assert action["name"] == "mcp.fixture.echo" and action["arguments"] == {
        "message": "topic=release"
    }


def test_executor_calls_are_denied_without_an_approval_path(tmp_path: Path) -> None:
    runner = executor(
        tmp_path, mcp={"fixture": {"command": sys.executable, "args": [str(MCP_FIXTURE)]}}
    )
    result = asyncio.run(runner.run(graph(MCP)))
    assert not result["ok"]
    assert "RT042" in json.dumps(result["run"])


def test_unconfigured_mcp_server_says_what_to_do(tmp_path: Path) -> None:
    result = asyncio.run(executor(tmp_path, assume_yes=True).run(graph(MCP)))
    assert not result["ok"] and "mcp.servers" in json.dumps(result["run"])


class FakeA2A(BaseHTTPRequestHandler):
    """A2A agent: message/send returns a working task, tasks/get completes it."""

    polls = 0

    def log_message(self, *_args):
        return

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.headers.get("authorization") == "Bearer agent-token"
        if request["method"] == "message/send":
            text = request["params"]["message"]["parts"][0]["text"]
            FakeA2A.last_text = text
            result = {"kind": "task", "id": "task-1", "status": {"state": "working"}}
        else:
            FakeA2A.polls += 1
            result = {
                "kind": "task",
                "id": request["params"]["id"],
                "status": {"state": "completed"},
                "artifacts": [
                    {"parts": [{"kind": "text", "text": f"answer to: {FakeA2A.last_text}"}]}
                ],
            }
        body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_a2a_executor_sends_polls_and_stores_the_answer(tmp_path: Path, monkeypatch) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeA2A)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("A2A_AGENT_TOKEN", "agent-token")
    try:
        document = graph(
            {
                "kind": "a2a",
                "url": f"http://127.0.0.1:{server.server_address[1]}/",
                "message": "Summarise ${{ inputs.topic }}",
                "token_env": "A2A_AGENT_TOKEN",
                "output": "answer",
            }
        )
        result = asyncio.run(executor(tmp_path, assume_yes=True).run(document))
    finally:
        server.shutdown()
        server.server_close()
    assert result["ok"], result["run"]["diagnostics"]
    assert result["run"]["outputs"]["answer"] == "answer to: Summarise release"
    assert FakeA2A.polls >= 1


@pytest.mark.parametrize(
    ("bad", "fragment"),
    [
        ({"kind": "ftp"}, "kind must be"),
        ({"kind": "mcp", "server": "x"}, "needs 'tool'"),
        ({"kind": "a2a", "url": "http://agents.example.com/"}, "https"),
        ({"kind": "mcp", "server": "x", "tool": "y", "output": "nope"}, "not a declared"),
    ],
)
def test_bad_executors_fail_validation(bad: dict, fragment: str) -> None:
    report = validate_graph(graph(bad))
    messages = [finding.message for finding in report.findings if finding.code == "MX001"]
    assert any(fragment in message for message in messages), messages


def test_every_gallery_example_is_listed_and_valid() -> None:
    gallery = (ROOT / "src" / "magent" / "docs" / "graph-gallery.md").read_text()
    examples = sorted((ROOT / "docs" / "examples" / "agraph").glob("*.agraph.yaml"))
    assert examples
    for path in examples:
        assert f"`{path.name}`" in gallery, f"{path.name} is missing from the gallery"
        assert validate_graph(path, strict=True).ok, path.name
