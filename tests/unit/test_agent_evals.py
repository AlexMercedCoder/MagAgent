from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from magent.agent_evals import (
    AGENT_EVAL_REPORT_SCHEMA,
    AGENT_EVAL_SCHEMA,
    compact_agent_eval_report,
    run_agent_eval_suite,
    run_agent_task,
    write_agent_eval_report,
)
from magent.evals import run_eval_suite


class RecordingStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def append(self, name: str, item: dict) -> dict:
        self.records.append((name, item))
        return item


def write_suite(path: Path, tasks: list[dict], targets: dict | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": AGENT_EVAL_SCHEMA,
                "name": "test-suite",
                "targets": targets or {"success_rate": 1, "artifact_success_rate": 1},
                "tasks": tasks,
            }
        ),
        encoding="utf-8",
    )


def test_agent_eval_suite_prepares_workspace_validates_and_records(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [
            {
                "id": "write-result",
                "category": "coding",
                "prompt": "Create result.json",
                "artifact_task": True,
                "files": {"seed.txt": "ready"},
                "validators": [
                    {"type": "file_exists", "path": "seed.txt"},
                    {"type": "json_valid", "path": "result.json"},
                    {"type": "response_contains", "text": "done"},
                    {"type": "audit_ok"},
                ],
            }
        ],
    )
    seen: list[tuple[str, str, int]] = []

    def runner(task, workspace, *, provider_id, model, timeout_seconds):
        assert (workspace / "seed.txt").read_text(encoding="utf-8") == "ready"
        (workspace / "result.json").write_text('{"ok": true}', encoding="utf-8")
        seen.append((provider_id, model, timeout_seconds))
        return {
            "ok": True,
            "response": "Done",
            "elapsed_ms": 12,
            "time_to_first_activity_ms": 3,
            "tool_calls": 1,
            "retries": 0,
            "usage": {"total_tokens": 8, "cached_tokens": 2, "cost_usd": 0.01},
            "changed_files": [str(workspace / "result.json")],
            "audit": {"ok": True, "permission_failures": []},
            "events": [{"event": "tool_call"}],
        }

    store = RecordingStore()
    report = run_agent_eval_suite(
        tmp_path,
        suite,
        store=store,
        runner=runner,
        provider_id="demo",
        model="small",
        timeout_seconds=9,
    )

    assert report["schema"] == AGENT_EVAL_REPORT_SCHEMA
    assert report["ok"] is True
    assert report["passed"] == report["total"] == 1
    assert report["artifact_success_rate"] == 1
    assert report["metrics"]["total_tokens"] == 8
    assert report["metrics"]["time_to_first_activity_ms"] == 3
    assert seen == [("demo", "small", 9)]
    assert store.records[0][0] == "agent_eval_runs"


def test_agent_eval_suite_enforces_targets_and_reports_failures(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [
            {
                "id": "missing",
                "prompt": "Create missing.txt",
                "artifact_task": True,
                "validators": [{"type": "file_exists", "path": "missing.txt"}],
            }
        ],
    )

    def runner(*_args, **_kwargs):
        return {"ok": True, "response": "claimed success", "audit": {}, "usage": {}}

    report = run_agent_eval_suite(tmp_path, suite, runner=runner)

    assert report["ok"] is False
    assert report["success_rate"] == 0
    assert report["artifact_success_rate"] == 0
    assert report["tasks"][0]["validations"][0]["exists"] is False


def test_agent_eval_suite_rejects_provider_error_response_even_when_artifact_exists(
    tmp_path: Path,
) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [
            {
                "id": "repair",
                "prompt": "Fix total.py",
                "files": {"total.py": "def total(values):\n    return sum(values)\n"},
                "validators": [{"type": "file_contains", "path": "total.py", "text": "sum"}],
            }
        ],
    )

    report = run_agent_eval_suite(
        tmp_path,
        suite,
        runner=lambda *_args, **_kwargs: {
            "ok": True,
            "response": "[Provider error: invalid model ID]",
            "error": "",
            "usage": {},
            "audit": {},
        },
    )

    assert report["ok"] is False
    assert report["passed"] == 0
    assert report["tasks"][0]["execution"]["error"] == "Provider error: invalid model ID"


def test_agent_eval_profiles_separate_core_from_optional_capabilities(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [
            {"id": "core", "prompt": "core"},
            {"id": "docs", "prompt": "docs", "profiles": ["full"]},
        ],
    )

    runner = lambda *_args, **_kwargs: {  # noqa: E731
        "ok": True,
        "response": "done",
        "usage": {},
        "audit": {},
    }
    core = run_agent_eval_suite(tmp_path, suite, runner=runner, profile="core")
    full = run_agent_eval_suite(tmp_path, suite, runner=runner, profile="full")

    assert (core["profile"], core["total"], core["skipped_tasks"]) == (
        "core",
        1,
        ["docs"],
    )
    assert (full["profile"], full["total"], full["skipped"]) == ("full", 2, 0)


def test_agent_eval_rejects_unknown_profile(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(suite, [])

    with pytest.raises(ValueError, match="core.*full"):
        run_agent_eval_suite(tmp_path, suite, profile="everything")


def test_agent_eval_validates_zip_member_and_sanitizes_workspace(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [
            {
                "id": "archive",
                "prompt": "Create workbook",
                "validators": [
                    {"type": "zip_contains", "path": "book.xlsx", "member": "xl/workbook.xml"}
                ],
            }
        ],
    )

    def runner(_task, workspace, **_kwargs):
        with zipfile.ZipFile(workspace / "book.xlsx", "w") as archive:
            archive.writestr("xl/workbook.xml", "<workbook />")
        return {
            "ok": True,
            "response": f"created {workspace}/book.xlsx",
            "changed_files": [str(workspace / "book.xlsx")],
            "usage": {},
            "audit": {},
        }

    report = run_agent_eval_suite(tmp_path, suite, runner=runner)

    assert report["ok"] is True
    assert report["tasks"][0]["execution"]["changed_files"] == ["./book.xlsx"]
    assert report["tasks"][0]["execution"]["response"] == "created ./book.xlsx"


def test_agent_eval_suite_contains_runner_crash_and_continues(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [
            {"id": "crash", "prompt": "crash"},
            {"id": "continue", "prompt": "continue", "validators": [{"type": "response_contains", "text": "ok"}]},
        ],
    )

    def runner(task, *_args, **_kwargs):
        if task["id"] == "crash":
            raise OSError("simulated provider disconnect")
        return {"ok": True, "response": "ok", "usage": {}, "audit": {}}

    report = run_agent_eval_suite(tmp_path, suite, runner=runner)

    assert report["passed"] == 1
    assert "simulated provider disconnect" in report["tasks"][0]["execution"]["error"]
    assert report["tasks"][1]["ok"] is True


def test_agent_eval_suite_rejects_fixture_path_escape(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [{"id": "escape", "prompt": "bad", "files": {"../escape.txt": "no"}}],
    )

    with pytest.raises(ValueError, match="escapes workspace"):
        run_agent_eval_suite(tmp_path, suite, runner=lambda *_args, **_kwargs: {"ok": True})

    assert not (tmp_path / "escape.txt").exists()


def test_agent_eval_suite_rejects_wrong_schema(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    suite.write_text('{"schema":"other","tasks":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="Expected schema"):
        run_agent_eval_suite(tmp_path, suite)


def test_scripted_agent_task_runs_real_tool_loop_without_user_state(tmp_path: Path) -> None:
    task = {
        "prompt": "Create hello.txt",
        "script": [
            {
                "tool": "write_file",
                "arguments": {
                    "path": "hello.txt",
                    "content": "Hello from a complete MagAgent evaluation artifact.\n",
                },
            },
            {"content": "Done"},
        ],
    }

    result = run_agent_task(task, tmp_path, timeout_seconds=10)

    assert result["ok"] is True
    assert result["response"] == "Done"
    assert "complete MagAgent evaluation" in (tmp_path / "hello.txt").read_text(encoding="utf-8")
    assert result["tool_calls"] == 1
    assert result["changed_files"]
    assert result["time_to_first_activity_ms"] is not None
    assert (tmp_path / ".magent-eval" / "logs").is_dir()


def test_permission_failure_validator_uses_audit_evidence(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [
            {
                "id": "blocked",
                "prompt": "Run blocked action",
                "validators": [{"type": "permission_failure"}],
            }
        ],
    )

    def runner(*_args, **_kwargs):
        return {
            "ok": True,
            "response": "Stopped",
            "audit": {"ok": False, "permission_failures": ["run_shell: permission required"]},
            "usage": {},
        }

    report = run_agent_eval_suite(tmp_path, suite, runner=runner)
    assert report["ok"] is True
    assert report["tasks"][0]["validations"][0]["permission_failures"]


def test_unknown_validator_fails_cleanly(tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(
        suite,
        [{"id": "unknown", "prompt": "x", "validators": [{"type": "mystery"}]}],
    )

    report = run_agent_eval_suite(
        tmp_path,
        suite,
        runner=lambda *_args, **_kwargs: {"ok": True, "response": "", "audit": {}, "usage": {}},
    )
    assert report["ok"] is False
    assert "unknown validator" in report["tasks"][0]["validations"][0]["error"]


def test_write_agent_eval_report_is_json_and_atomic(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "report.json"
    path = write_agent_eval_report({"ok": True, "value": {1, 2}}, target)

    assert path == str(target.resolve())
    assert json.loads(target.read_text(encoding="utf-8"))["ok"] is True
    assert not target.with_suffix(".json.tmp").exists()


def test_compact_agent_eval_report_removes_verbose_runtime_details() -> None:
    source = {
        "tasks": [
            {
                "execution": {
                    "events": [{"event": "tool_call"}],
                    "session_id": "secret-local-id",
                    "response": "x" * 1200,
                    "usage": {"total_tokens": 10},
                }
            }
        ]
    }

    result = compact_agent_eval_report(source)

    assert "events" not in result["tasks"][0]["execution"]
    assert "session_id" not in result["tasks"][0]["execution"]
    assert result["tasks"][0]["execution"]["response"].endswith("...")
    assert source["tasks"][0]["execution"]["events"]


def test_run_eval_suite_dispatches_agent_schema(monkeypatch, tmp_path: Path) -> None:
    suite = tmp_path / "suite.json"
    write_suite(suite, [])
    calls = []

    def fake(root, path, store=None):
        calls.append((Path(root), Path(path), store))
        return {"ok": True, "suite": "agent"}

    monkeypatch.setattr("magent.agent_evals.run_agent_eval_suite", fake)
    marker = object()
    result = run_eval_suite(tmp_path, suite, store=marker)

    assert result == {"ok": True, "suite": "agent"}
    assert calls == [(tmp_path.resolve(), suite, marker)]
