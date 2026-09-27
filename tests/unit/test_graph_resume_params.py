"""G-14: resuming a graph run never passes the "[REDACTED]" marker as a parameter.

A run record replaces the value of every declared graph secret with
"[REDACTED]", including inside parameters. `magent graph resume` rebound the
saved parameters, so the resumed run received the marker instead of the
secret. Redacted parameters must now be supplied again (`--param`,
`--params`, `--param-file`, or a hidden prompt on a terminal), and the executor
refuses the marker from any caller.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent.agraph.document import write_graph
from magent.agraph.execute import GraphRunError
from magent.agraph.output import emit_output
from tests.unit.test_agraph import executor, graph

SECRET = "s3cret-deploy-value"


def secret_graph() -> dict:
    document = graph()
    document["secrets"] = [
        {"name": "deploy_token", "description": "Deployment credential.", "required": True}
    ]
    document["params"] = {
        "token": {"type": "string", "description": "Deploy credential."},
        "region": {"type": "string", "description": "Target region.", "default": "us"},
    }
    document["nodes"]["work"]["inputs"] = {
        "token": {"type": "string", "description": "Credential.", "from": "params.token"}
    }
    return document


@pytest.fixture(autouse=True)
def deploy_secret(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOY_TOKEN", SECRET)


def failing_then_recording(seen: list[str], *, fail_first: bool = True):
    calls = {"n": 0}

    async def runner(_node, prompt, _route, _task):
        calls["n"] += 1
        seen.append(prompt)
        if fail_first and calls["n"] == 1:
            raise RuntimeError("provider unavailable")
        emit_output("result", "done")
        return ""

    return runner


def test_executor_refuses_the_redaction_marker(tmp_path: Path) -> None:
    seen: list[str] = []
    runner = failing_then_recording(seen)
    first = asyncio.run(executor(tmp_path, runner).run(secret_graph(), params={"token": SECRET}))
    assert not first["ok"]
    assert first["run"]["metadata"] is not None
    saved = first["run"].get("params") or {}
    assert saved.get("token") == "[REDACTED]"

    with pytest.raises(GraphRunError) as raised:
        asyncio.run(
            executor(tmp_path, runner).run(secret_graph(), params=saved, resume_record=first["run"])
        )
    assert raised.value.code == "RT055"
    assert "token" in str(raised.value)
    assert all("[REDACTED]" not in prompt for prompt in seen)


def _cli_run(tmp_path: Path, monkeypatch):
    """Start a real run through the CLI that fails once, so it can be resumed."""
    from magent.agraph import execute as execute_module
    from magent.cli import main as cli_main

    runner = CliRunner()
    runner.invoke(cli_main.app, ["user", "create", "g14"])
    assert runner.invoke(cli_main.app, ["user", "switch", "g14"]).exit_code == 0
    path = tmp_path / "secret.agraph.yaml"
    write_graph(secret_graph(), path)
    seen: list[str] = []
    fake = failing_then_recording(seen)

    async def default_runner(self, node_id, prompt, route, task_id):
        return await fake(node_id, prompt, route, task_id)

    monkeypatch.setattr(execute_module.GraphExecutor, "_default_agent_runner", default_runner)
    started = runner.invoke(
        cli_main.app,
        [
            "graph",
            "run",
            str(path),
            "--project",
            str(tmp_path),
            "--params",
            json.dumps({"token": SECRET}),
            "--json",
        ],
    )
    run_id = json.loads(started.output[started.output.index("{") :])["run"]["run_id"]
    return runner, cli_main, run_id, seen


def test_resume_without_the_secret_is_refused_with_the_names(tmp_path: Path, monkeypatch) -> None:
    runner, cli_main, run_id, seen = _cli_run(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_main.app, ["graph", "resume", run_id, "--project", str(tmp_path), "--json"]
    )
    assert result.exit_code == 2, result.output
    assert "token" in result.output and "--param token=" in result.output
    assert all("[REDACTED]" not in prompt for prompt in seen)


def test_resume_with_the_secret_resupplied_uses_it(tmp_path: Path, monkeypatch) -> None:
    runner, cli_main, run_id, seen = _cli_run(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_main.app,
        [
            "graph",
            "resume",
            run_id,
            "--project",
            str(tmp_path),
            "--param",
            f"token={SECRET}",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert SECRET in seen[-1]
    assert all("[REDACTED]" not in prompt for prompt in seen)
    assert SECRET not in result.output  # still redacted in the new record


def test_resume_reads_secrets_from_a_param_file(tmp_path: Path, monkeypatch) -> None:
    runner, cli_main, run_id, seen = _cli_run(tmp_path, monkeypatch)
    secrets_file = tmp_path / "params.json"
    secrets_file.write_text(json.dumps({"token": SECRET}), encoding="utf-8")
    result = runner.invoke(
        cli_main.app,
        [
            "graph",
            "resume",
            run_id,
            "--project",
            str(tmp_path),
            "--param-file",
            str(secrets_file),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert SECRET in seen[-1]
