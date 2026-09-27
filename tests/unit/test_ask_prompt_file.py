"""G-11: `magent ask --prompt-file` and a clean stdout in --json mode."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent.cli import main as cli_main
from tests.unit.test_cli import redirect_config

ROOT = Path(__file__).resolve().parents[2]
RUN_CLI = "import sys; from magent.cli.main import app; sys.argv[0] = 'magent'; app()"


def _magent(home: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(ROOT / "src"),
        "NO_COLOR": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", RUN_CLI, *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
        timeout=180,
        check=False,
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    assert _magent(tmp_path, "user", "create", "demo").returncode == 0
    for key, value in (
        ("memory.extraction_provider", "mock"),
        ("memory.semantic_enabled", "false"),
    ):
        assert _magent(tmp_path, "config", "set", key, value).returncode == 0
    return tmp_path


def test_prompt_file_delivers_a_megabyte_prompt_without_argv(home: Path) -> None:
    prompt = home / "prompt.md"
    marker = "UNIQUE-MARKER-7d1f"
    prompt.write_text(marker + " " + ("lorem ipsum " * 90_000), encoding="utf-8")
    assert prompt.stat().st_size > 1_000_000

    result = _magent(
        home,
        "ask",
        "--prompt-file",
        str(prompt),
        "--provider",
        "mock",
        "--project",
        str(home),
        "--json",
        "--events",
    )

    assert result.returncode == 0, result.stderr[-2000:]
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, "stdout must carry only the result document"
    payload = json.loads(lines[0])
    assert payload["response"].startswith("[MagAgent mock provider")
    assert marker in payload["response"]
    assert payload["events"][0] == {"type": "user_message", "content": prompt.read_text()}
    assert "skills" not in result.stdout


def test_json_stdout_is_parseable_as_a_whole(home: Path) -> None:
    result = _magent(home, "ask", "hi", "--provider", "mock", "--json")
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(result.stdout)["ok"] is True
    assert "Loaded" not in result.stdout


@pytest.fixture
def cli(monkeypatch, tmp_path: Path):
    redirect_config(monkeypatch, tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "alex"]).exit_code == 0
    return runner, tmp_path


@pytest.mark.parametrize(
    ("setup", "args", "message"),
    [
        (None, ["ask"], "Missing task"),
        (None, ["ask", "   "], "Missing task"),
        (None, ["ask", "--prompt-file", "missing.md"], "not found"),
        ("empty", ["ask", "--prompt-file", "{path}"], "is empty"),
        ("binary", ["ask", "--prompt-file", "{path}"], "UTF-8"),
        ("text", ["ask", "task", "--prompt-file", "{path}"], "not both"),
        ("dir", ["ask", "--prompt-file", "{dir}"], "directory"),
    ],
)
def test_prompt_file_usage_errors_exit_2(cli, setup, args, message) -> None:
    runner, root = cli
    path = root / "prompt.md"
    if setup == "empty":
        path.write_text("  \n", encoding="utf-8")
    elif setup == "binary":
        path.write_bytes(b"\xff\xfe\x00bad")
    elif setup == "text":
        path.write_text("hello", encoding="utf-8")
    resolved = [item.format(path=path, dir=root) if "{" in item else item for item in args]
    result = runner.invoke(cli_main.app, resolved)
    assert result.exit_code == 2, result.output
    assert message in result.output


def test_prompt_file_size_limit(cli, monkeypatch) -> None:
    runner, root = cli
    monkeypatch.setattr(cli_main, "MAX_PROMPT_FILE_BYTES", 10)
    path = root / "big.md"
    path.write_text("x" * 20, encoding="utf-8")
    result = runner.invoke(cli_main.app, ["ask", "--prompt-file", str(path)])
    assert result.exit_code == 2 and "limit" in result.output


def test_stdio_broker_writes_to_the_captured_machine_stream(tmp_path: Path, monkeypatch) -> None:
    from magent.approval_broker import start_stdio_broker
    from magent.workbench_store import WorkbenchStore

    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "test"
    store.root = tmp_path
    store.warnings = []
    import signal

    machine = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    previous = signal.getsignal(signal.SIGTERM)
    try:
        _broker, publish = start_stdio_broker(store, project=tmp_path, stream="s", out=machine)
    finally:
        signal.signal(signal.SIGTERM, previous)
    status = io.StringIO()
    monkeypatch.setattr(sys, "stdout", status)
    publish({"type": "approval.requested", "sequence": 1})
    assert json.loads(machine.getvalue()) == {"type": "approval.requested", "sequence": 1}
    assert status.getvalue() == ""


def test_emit_machine_json_is_single_line_off_a_terminal() -> None:
    out = io.StringIO()
    cli_main._emit_machine_json({"a": 1, "b": [1, 2]}, out)
    assert out.getvalue() == '{"a": 1, "b": [1, 2]}\n'
