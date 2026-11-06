"""Regressions for the 1.4.1 fixes found by the Appendix B walkthrough (M1-M5)."""

from __future__ import annotations

import asyncio
import re
import sys
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from magent import config as magent_config
from magent.agraph.criteria import CriterionResult
from magent.agraph.execute import GraphExecutor, _failed_feedback, _node_prompt
from magent.agraph.status import run_summary
from magent.config import DEFAULT_GLOBAL_CONFIG, Config
from magent.providers import mock
from magent.workbench_store import WorkbenchStore

ROOT = Path(__file__).resolve().parents[2]
EXE = sys.executable


def _graph(node: dict) -> dict:
    return {
        "ags_version": "1.0",
        "kind": "AgenticGraph",
        "id": "tests/release-141",
        "title": "Release 1.4.1 regressions",
        "objective": "Exercise one node.",
        "version": "1.0.0",
        "requires_conformance": 1,
        "entrypoints": ["work"],
        "nodes": {
            "work": {
                "type": "task",
                "title": "Do work",
                "description": "Produce a bounded result.",
                "outputs": {"result": {"type": "string", "description": "The result."}},
                "requirements": {"tools": [], "permissions": []},
                **node,
            }
        },
        "outputs": {
            "result": {
                "type": "string",
                "description": "Final result.",
                "from": "nodes.work.outputs.result",
            }
        },
    }


async def _emit(*_args):
    return {"outputs": {"result": "done"}}


def _executor(tmp_path: Path, *, permissions: dict | None = None, **kwargs) -> GraphExecutor:
    config = {**DEFAULT_GLOBAL_CONFIG, "permissions": {**DEFAULT_GLOBAL_CONFIG["permissions"]}}
    config["defaults"] = {**DEFAULT_GLOBAL_CONFIG["defaults"], "permission_mode": "balanced"}
    config["permissions"].update(permissions or {})
    return GraphExecutor(
        username="test",
        config=Config(config),
        project=tmp_path,
        store=WorkbenchStore(tmp_path / "store"),
        agent_runner=_emit,
        **kwargs,
    )


# M1: LiteLLM 1.108 imports the MCP SDK on every completion.


def test_core_dependencies_include_the_mcp_sdk() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = {re.split(r"[\s<>=!~\[;]", item, maxsplit=1)[0] for item in project["dependencies"]}
    assert "mcp" in names


def test_core_install_ci_job_runs_a_mock_completion() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    job = workflow.split("core-install:", 1)[1].split("\n  vscode-extension:", 1)[0]
    assert 'pip install .' in job and "[" not in job.split("pip install .", 1)[1].split()[0]
    assert "--provider mock" in job


# M2: graph skill preflight uses the session's search path.


def _project_skill(project: Path, name: str) -> None:
    skill = project / ".magent" / "skills" / name / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        f"---\nname: {name}\ndescription: A project-only skill.\n---\n\nDo the thing.\n",
        encoding="utf-8",
    )


def test_project_only_skill_satisfies_requirements(tmp_path: Path) -> None:
    _project_skill(tmp_path, "project-only-skill-141")
    document = _graph({"requirements": {"tools": [], "skills": ["project-only-skill-141"]}})
    result = asyncio.run(_executor(tmp_path).run(document))
    assert result["ok"], result["run"]["diagnostics"]


def test_missing_skill_still_fails_with_rt012(tmp_path: Path) -> None:
    document = _graph({"requirements": {"tools": [], "skills": ["no-such-skill-141"]}})
    result = asyncio.run(_executor(tmp_path).run(document))
    assert not result["ok"]
    assert any(
        item["code"] == "RT012" and "no-such-skill-141" in item["message"]
        for item in result["run"]["diagnostics"]
    )


# M3: command criteria apply the policy allowlist and say why they were denied.


def _command_node(tmp_path: Path, command: str, grant: str) -> dict:
    (tmp_path / "check.py").write_text("print('criterion ran')\n", encoding="utf-8")
    return {
        "requirements": {"tools": [], "permissions": [f"shell:exec:{grant}"]},
        "success": {
            "summary": "The check passes.",
            "criteria": [
                {
                    "id": "check",
                    "kind": "command",
                    "description": "The check script exits zero.",
                    "run": command,
                    "expect_exit_code": 0,
                }
            ],
        },
    }


def _criterion(result: dict) -> dict:
    return result["run"]["nodes"][0]["attempts"][-1]["success"]["results"][0]


def test_command_criterion_granted_and_allowlisted_runs_without_a_prompt(tmp_path: Path) -> None:
    node = _command_node(tmp_path, f"{EXE} check.py", f"{EXE}*")
    graph_executor = _executor(
        tmp_path, permissions={"allowed_shell_patterns": [f"{EXE} *"]}, assume_yes=True
    )
    result = asyncio.run(graph_executor.run(_graph(node)))
    assert result["ok"], result["run"]["diagnostics"]
    assert "criterion ran" in _criterion(result)["evidence"]


def test_denied_command_criterion_records_who_denied_it(tmp_path: Path) -> None:
    node = _command_node(tmp_path, f"{EXE} check.py", f"{EXE}*")
    result = asyncio.run(_executor(tmp_path, assume_yes=True).run(_graph(node)))
    assert not result["ok"]
    criterion = _criterion(result)
    assert "RT017" in criterion["error"] and f"{EXE} check.py" in criterion["error"]
    assert "balanced" in criterion["evidence"] and "allowed_shell_patterns" in criterion["evidence"]
    [diagnostic] = [item for item in result["run"]["diagnostics"] if item["code"] == "RT017"]
    assert diagnostic["node_id"] == "work"


def test_policy_allowlist_needs_the_graph_grant_too(tmp_path: Path) -> None:
    node = _command_node(tmp_path, f"{EXE} check.py", "grep*")
    graph_executor = _executor(
        tmp_path, permissions={"allowed_shell_patterns": [f"{EXE} *"]}, assume_yes=True
    )
    result = asyncio.run(graph_executor.run(_graph(node)))
    assert not result["ok"]
    assert "shell:exec" in _criterion(result)["error"]


def test_policy_still_outranks_the_graph(tmp_path: Path) -> None:
    # An unparseable command is blocked outright; no allowlist or grant lifts it.
    node = _command_node(tmp_path, "echo 'unterminated", "*")
    graph_executor = _executor(
        tmp_path, permissions={"allowed_shell_patterns": ["*"]}, assume_yes=True
    )
    result = asyncio.run(graph_executor.run(_graph(node)))
    assert not result["ok"]
    assert "RT017" in _criterion(result)["error"]


# M4: AGS 10.3 retry feedback and node instructions.


def test_prompt_includes_instructions_and_failed_criterion_description() -> None:
    node = {
        "title": "Migrate",
        "description": "Migrate the module.",
        "instructions": "Follow the migrate-module skill for ${{ inputs.target }}.",
        "success": {
            "criteria": [
                {
                    "id": "no_db_import",
                    "kind": "command",
                    "description": "order-service.js no longer imports ../db.js.",
                }
            ]
        },
    }
    results = [
        CriterionResult(
            "no_db_import", "command", "required", False, evidence="1:import { query }"
        )
    ]
    feedback = _failed_feedback(results, "", node["success"]["criteria"])
    prompt = _node_prompt(node, {"target": "order-service.js"}, feedback)
    assert "Follow the migrate-module skill for order-service.js." in prompt
    assert "order-service.js no longer imports ../db.js." in prompt
    assert "1:import { query }" in prompt


# M5: spec diagnostic codes, the run summary, and the mock docstring.


def test_unbound_graph_output_uses_rt041(tmp_path: Path) -> None:
    async def nothing(*_args):
        return {"outputs": {}}

    document = _graph({"outputs": {"result": {"type": "string", "description": "x"}}})
    graph_executor = _executor(tmp_path)
    graph_executor.agent_runner = nothing
    result = asyncio.run(graph_executor.run(document))
    codes = {item["code"] for item in result["run"]["diagnostics"]}
    assert {"RT033", "RT041"} <= codes
    assert "RT024" not in codes and "RT001" not in codes


def test_cli_summary_counts_a_failed_run(tmp_path: Path, monkeypatch) -> None:
    from magent.cli.commands import graph as graph_cmd
    from magent.cli.main import app

    run = {
        "run_id": "agraph_x",
        "status": "failed",
        "nodes": [{"node_id": "a", "status": "succeeded"}, {"node_id": "b", "status": "failed"}],
        "diagnostics": [],
        "metadata": {
            "x-magagent-summary": {"succeeded": ["a"], "failed": ["b"], "skipped": []}
        },
    }
    assert run_summary(run)["failed"] == ["b"]

    class FakeExecutor:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run(self, *args, **kwargs):
            return {"ok": False, "run": run}

    monkeypatch.setattr(graph_cmd, "GraphExecutor", FakeExecutor)
    cfg_dir = tmp_path / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", cfg_dir / "users" / "current")
    magent_config.create_user("release-141")
    magent_config.set_current_user("release-141")
    path = tmp_path / "g.agraph.json"
    path.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(app, ["graph", "run", str(path), "--project", str(tmp_path)])
    assert "Succeeded: 1 | Failed/blocked: 1 | Skipped: 0" in result.output, result.output


def test_mock_docstring_matches_scripted_replies(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "script.json"
    script.write_text('[{"content": "Verbatim reply."}]', encoding="utf-8")
    monkeypatch.setenv(mock.SCRIPT_ENV, str(script))
    step = mock.scripted_step([{"role": "user", "content": "hi"}])
    assert step == {"content": "Verbatim reply."}
    assert "replayed exactly as written" in (mock.__doc__ or "")
