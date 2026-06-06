from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from magent import browser, evals, github_workflows, sandbox, workbench
from magent.cli import main as cli_main
from magent.tools.executor import ToolExecutor
from magent.workbench import WorkbenchStore
from magent.workbench_cockpit import cockpit_state

runner = CliRunner()


def test_sandbox_preview_and_copy_execution(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "check.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("sandbox-test")
    plan = workbench.save_execution_plan(
        store,
        project,
        "Run smoke",
        commands=["python check.py"],
        include_diff=False,
    )

    preview = sandbox.sandbox_plan_preview(store, plan["id"], mode="copy")
    result = sandbox.execute_plan_sandbox(store, plan["id"], mode="copy")

    assert "python check.py" in preview["commands"]
    assert result["ok"] is True
    assert store.read("sandbox_runs", [])[0]["plan_id"] == plan["id"]


def test_eval_suite_init_list_run_and_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("eval-test")
    initialized = evals.init_evals(tmp_path)
    (tmp_path / "evals" / "magagent-evals.json").write_text(
        json.dumps(
            {
                "name": "sample-python-repair",
                "tasks": [{"id": "smoke", "prompt": "Run smoke", "commands": ["python -c 'print(1)'"]}],
            }
        ),
        encoding="utf-8",
    )
    suites = evals.list_eval_suites(tmp_path)
    report = evals.run_eval_suite(tmp_path, "evals/magagent-evals.json", store=store)

    assert initialized["ok"] is True
    assert suites[0]["tasks"] == 1
    assert report["ok"] is True
    assert evals.eval_report(store)[0]["suite"] == "sample-python-repair"


def test_github_workflows_parse_gh_json(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, cwd, text, capture_output, timeout):
        payload = json.dumps([{"number": 1, "title": "Issue"}])
        return subprocess.CompletedProcess(cmd, 0, payload, "")

    monkeypatch.setattr(github_workflows.subprocess, "run", fake_run)
    result = github_workflows.list_issues(tmp_path, limit=1)

    assert result["ok"] is True
    assert result["issues"][0]["number"] == 1


def test_browser_helpers_report_missing_playwright(monkeypatch) -> None:
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    import asyncio

    result = asyncio.run(browser.browser_snapshot("https://example.com"))

    assert result["ok"] is False
    assert "Playwright" in result["error"]


def test_cockpit_state_collects_actionable_surfaces(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("cockpit-test")
    store.append("tasks", {"title": "Review cockpit", "status": "open"})

    state = cockpit_state(store, project)

    assert state["ok"] is True
    assert state["memory_inbox"]
    assert "release_check" in state


def test_cli_new_release_016_commands(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = WorkbenchStore("cli-016")
    monkeypatch.setattr(cli_main, "_store", lambda: store)

    plan = workbench.save_execution_plan(store, project, "Run smoke", commands=["python -c 'print(1)'"], include_diff=False)
    sandboxed = runner.invoke(cli_main.app, ["plan-sandbox", plan["id"], "--mode", "copy", "--dry-run"])
    eval_init = runner.invoke(cli_main.app, ["eval", "init", "--project", str(project)])
    eval_list = runner.invoke(cli_main.app, ["eval", "list", "--project", str(project)])

    assert sandboxed.exit_code == 0
    assert json.loads(sandboxed.output)["mode"] == "copy"
    assert eval_init.exit_code == 0
    assert eval_list.exit_code == 0
    assert json.loads(eval_list.output)["suites"][0]["tasks"] == 1


def test_tool_executor_exposes_browser_tools(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    executor = ToolExecutor(str(tmp_path), username="tool-test")
    names = {item["function"]["name"] for item in executor.get_tool_definitions_for_message("take a browser screenshot")}

    assert "browser_snapshot" in names
    assert "browser_screenshot" in names
