"""G-10: parallel read-only tool calls and the edit-quality benchmark."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from magent.agent_runtime.tool_loop import PARALLEL_READ_ONLY_TOOLS, ToolLoopRuntimeMixin
from magent.cli import main as cli_main
from magent.edit_quality import CASES, run_edit_quality


def _call(name: str, **arguments) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"c-{name}", function=SimpleNamespace(name=name, arguments=json.dumps(arguments))
    )


class FakeRuntime(ToolLoopRuntimeMixin):
    def __init__(self, limit: int) -> None:
        self.config = SimpleNamespace(max_parallel_read_tools=limit)
        self.turn_count = 1
        self.logger = SimpleNamespace(log_activity_event=lambda _event: None)
        self.active = 0
        self.peak = 0
        self.order: list[str] = []

    async def _execute_tool_call(self, name: str, arguments: dict) -> dict:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.05)
        self.active -= 1
        self.order.append(arguments.get("path", name))
        return {"ok": True, "path": arguments.get("path")}


def test_only_runs_of_read_only_calls_are_grouped_and_run_with_a_bound() -> None:
    runtime = FakeRuntime(limit=2)
    calls = [
        _call("read_file", path="a"),
        _call("read_file", path="b"),
        _call("write_file", path="w", content="x"),
        _call("list_dir", path="c"),
        _call("read_file", path="d"),
        _call("read_file", path="e"),
        _call("run_shell", command="ls"),
        _call("read_file", path="f"),
    ]
    segments = runtime._read_only_segments(calls)
    # The write, the shell call and the lone trailing read are left for the
    # serial loop; reads never jump across a write.
    assert segments == {0: [0, 1], 3: [3, 4, 5]}
    results = asyncio.run(runtime._run_read_segment(calls, segments[3]))
    assert sorted(results) == [3, 4, 5]
    assert all(results[index][0]["ok"] for index in results)
    assert runtime.peak == 2
    assert sorted(runtime.order) == ["c", "d", "e"]  # only the requested segment ran


def test_parallelism_can_be_disabled() -> None:
    runtime = FakeRuntime(limit=1)
    calls = [_call("read_file", path="a"), _call("read_file", path="b")]
    assert runtime._read_only_segments(calls) == {}


def test_read_only_set_excludes_anything_that_writes_or_runs() -> None:
    assert not PARALLEL_READ_ONLY_TOOLS & {
        "write_file",
        "edit_file",
        "delete_file",
        "run_shell",
        "run_python",
        "db_execute",
        "http_request",
        "web_fetch",
    }


def test_edit_quality_benchmark_passes_every_case() -> None:
    report = run_edit_quality()
    failures = [case["id"] for case in report["cases"] if not case["passed"]]
    assert failures == [] and report["total"] == len(CASES) and report["score"] == 1.0


def test_edit_quality_cli(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = CliRunner().invoke(
        cli_main.app, ["eval", "edit-quality", "--json", "--report-out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["schema"] == "magent.edit-quality.v1"


def test_crlf_and_non_utf8_regressions(tmp_path: Path) -> None:
    from magent.tools.executor import ToolExecutor

    tools = ToolExecutor(str(tmp_path), permission_mode="yolo", interactive_permissions=False)
    crlf = tmp_path / "win.txt"
    crlf.write_bytes(b"a\r\nb\r\n")
    assert asyncio.run(tools.edit_file("win.txt", "b", "c"))["ok"]
    assert crlf.read_bytes() == b"a\r\nc\r\n"
    latin = tmp_path / "latin.txt"
    latin.write_bytes(b"caf\xe9\nx = 1\n")
    refused = asyncio.run(tools.edit_file("latin.txt", "x = 1", "x = 2"))
    assert refused["ok"] is False and "not valid UTF-8" in refused["error"]
    assert latin.read_bytes() == b"caf\xe9\nx = 1\n"
