"""G-8 (M6): offline end-to-end workflow fixtures.

Each workflow runs the real CLI or runtime against the offline `mock`
provider in scripted mode (MAGENT_MOCK_SCRIPT), so the model's tool calls are
fixed while everything else (tool loop, permissions, approval broker, graph
executor, subagents, the RPC gateway, cancellation) is the production code.
Scripts and the graph live in tests/fixtures/workflows/.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# Several subprocess runs per test; they run in the slow CI job.
pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "workflows"
HUMAN = {"id": "fixture-user", "type": "human", "authenticated_by": "test"}


def _env(script: str) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "NO_COLOR": "1",
        "MAGENT_MOCK_SCRIPT": str(FIXTURES / script),
    }


def _magent(*args: str, cwd: Path, script: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "magent", *args],
        cwd=cwd,
        env=_env(script),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        **kwargs,
    )


@pytest.fixture(scope="module")
def user() -> str:
    """One MagAgent user on the test HOME, set up for offline runs."""
    for args in (
        ("user", "create", "fixtures"),
        ("config", "set", "defaults.provider", "mock"),
        ("config", "set", "defaults.model", "offline-demo"),
        ("config", "set", "memory.extraction_provider", "mock"),
        ("config", "set", "memory.extraction_model", "offline-demo"),
        ("config", "set", "memory.semantic_enabled", "false"),
        ("config", "set", "memory.auto_write", "false"),
    ):
        result = _magent(*args, cwd=ROOT, script="edit.script.json")
        assert result.returncode == 0, result.stderr
    return "fixtures"


@pytest.fixture
def project(tmp_path: Path, user: str) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


def _ask(project: Path, script: str, prompt: str, *extra: str) -> dict:
    result = _magent(
        "ask",
        prompt,
        "--provider",
        "mock",
        "--project",
        str(project),
        "--json",
        "--events",
        *extra,
        cwd=project,
        script=script,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout)


def test_edit_workflow(project: Path) -> None:
    payload = _ask(
        project, "edit.script.json", "Fix the greeting typo", "--permission-mode", "yolo"
    )
    assert (project / "greet.py").read_text() == "def greet(name):\n    return 'Hello, ' + name\n"
    assert payload["audit"]["ok"] is True
    assert any(event["type"] == "file_touched" for event in payload["events"])


def test_test_workflow_writes_code_and_a_passing_test(project: Path) -> None:
    payload = _ask(project, "test.script.json", "Add calc with a test", "--permission-mode", "yolo")
    commands = [event["command"] for event in payload["events"] if event["type"] == "command"]
    assert any("pytest" in command for command in commands)
    rerun = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rerun.returncode == 0, rerun.stdout


def test_artifact_workflow(project: Path) -> None:
    payload = _ask(
        project, "artifact.script.json", "Write the weekly report", "--permission-mode", "yolo"
    )
    assert "<h1>Weekly report</h1>" in (project / "report.html").read_text()
    svg = (project / "chart.svg").read_text()
    assert svg.startswith("<svg") and "12 passed" in svg
    assert payload["response"] == "Wrote report.html and chart.svg."


def _decide_from_stdout(process: subprocess.Popen[str], decision: str) -> dict:
    """Read NDJSON from a --approval-stdio run, answer its first request."""
    from aais import create_decision

    assert process.stdout is not None and process.stdin is not None
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            break
        try:
            envelope = json.loads(line)
        except ValueError:
            continue
        if envelope.get("type") == "approval.requested":
            decided = create_decision(
                envelope, decision=decision, scope="once", actor=HUMAN, sequence=1
            )
            process.stdin.write(json.dumps(decided) + "\n")
            process.stdin.flush()
            return envelope
    raise AssertionError("no approval.requested envelope was published")


def test_approval_inside_a_graph(project: Path) -> None:
    graph = project / "approval.agraph.yaml"
    graph.write_text((FIXTURES / "approval.agraph.yaml").read_text())
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "magent",
            "graph",
            "run",
            str(graph),
            "--project",
            str(project),
            "--json",
            "--approval-stdio",
        ],
        cwd=project,
        env=_env("graph-approval.script.json"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        request = _decide_from_stdout(process, "approve")
        assert request["request"]["action"]["arguments"]["command"] == "mkdir build-output"
        out, err = process.communicate(timeout=180)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert process.returncode == 0, err[-3000:]
    assert (project / "build-output").is_dir()


def test_denied_approval_inside_a_graph_does_not_run(project: Path) -> None:
    graph = project / "approval.agraph.yaml"
    graph.write_text((FIXTURES / "approval.agraph.yaml").read_text())
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "magent",
            "graph",
            "run",
            str(graph),
            "--project",
            str(project),
            "--json",
            "--approval-stdio",
        ],
        cwd=project,
        env=_env("graph-approval.script.json"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _decide_from_stdout(process, "deny")
        process.communicate(timeout=180)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert not (project / "build-output").exists()


def test_approval_inside_a_subagent(project: Path, monkeypatch) -> None:
    from magent.approval_broker import ApprovalBroker
    from magent.config import load_config
    from magent.providers import build_provider
    from magent.subagents import SubAgentRunner
    from magent.workbench_store import WorkbenchStore

    monkeypatch.setenv("MAGENT_MOCK_SCRIPT", str(FIXTURES / "subagent-approval.script.json"))
    config = load_config("fixtures")
    broker = ApprovalBroker(WorkbenchStore("fixtures"), project=project)
    published: list[dict] = []

    def prompt(description: str, tier: int, action: dict | None = None) -> str:
        return broker.request_prompt(
            description,
            tier,
            action,
            origin={"session_id": "subagent-fixture"},
            publish=published.append,
            timeout=120,
        )

    def answer() -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            requested = [item for item in published if item.get("type") == "approval.requested"]
            if requested:
                broker.decide(
                    requested[0]["request"]["id"], decision="approve", scope="once", actor=HUMAN
                )
                return
            time.sleep(0.05)

    threading.Thread(target=answer, daemon=True).start()
    provider = build_provider("mock", "offline-demo", None, {})
    runner = SubAgentRunner(
        username="fixtures",
        provider=provider,
        extraction_provider=provider,
        cwd=str(project),
        config=config,
        interactive_permissions=False,
        permission_prompt=prompt,
    )
    import asyncio

    task = asyncio.run(runner.spawn("sub-1", "Create the sub-output directory"))
    broker.close()
    assert task.done and not task.error, task.error
    assert (project / "sub-output").is_dir()
    assert (
        published
        and published[0]["request"]["action"]["arguments"]["command"] == "mkdir sub-output"
    )


def test_cancel_mid_tool_stops_the_run_and_the_tool_process(project: Path) -> None:
    from magent.rpc_gateway import Gateway

    marker = "time.sleep(37.25)"
    gateway = Gateway(
        token="c" * 32,
        roots=[project],
        env=_env("cancel.script.json"),
    )
    try:
        gateway.stream_start(
            {
                "id": "cancel-1",
                "args": [
                    "ask",
                    "Run the long job",
                    "--provider",
                    "mock",
                    "--permission-mode",
                    "yolo",
                    "--project",
                    str(project),
                ],
            }
        )
        after, seen = 0, []
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not _running(marker):
            page = gateway.stream_events({"id": "cancel-1", "after": after, "wait_ms": 1000})
            after = page["next"]
            seen.extend(page["events"])
        assert _running(marker), seen
        assert gateway.cancel_magent_stream({"id": "cancel-1"}) is True
        page = gateway.stream_events({"id": "cancel-1", "after": after, "wait_ms": 20000})
        while not page["done"] and time.monotonic() < deadline:
            page = gateway.stream_events({"id": "cancel-1", "after": page["next"], "wait_ms": 2000})
        assert page["done"] and page["result"]["ok"] is False
        stop = time.monotonic() + 10
        while _running(marker) and time.monotonic() < stop:
            time.sleep(0.1)
        assert not _running(marker), "the tool's child process outlived the cancel"
    finally:
        gateway.shutdown()


def _running(marker: str) -> bool:
    import re

    result = subprocess.run(
        ["pgrep", "-f", re.escape(marker)], capture_output=True, text=True, check=False
    )
    return bool(result.stdout.strip())
