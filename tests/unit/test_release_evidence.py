from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent.cli.main import app
from magent.release_evidence import build_release_evidence, write_release_evidence


def test_release_evidence_records_local_proof(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "wheel.whl"
    artifact.write_bytes(b"wheel")
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(json.dumps({"ok": True, "passed": 30, "total": 30}), encoding="utf-8")
    memory_path = tmp_path / "memory.json"
    memory_path.write_text('{"ok": true, "schema": "magent.memory-eval.v2"}', encoding="utf-8")
    performance_path = tmp_path / "performance.json"
    performance_path.write_text(
        '{"ok": true, "schema": "magent.performance-budget.v1"}', encoding="utf-8"
    )
    supply_path = tmp_path / "supply.json"
    supply_path.write_text('{"ok": true, "schema": "magent.supply-chain.v1"}', encoding="utf-8")
    monkeypatch.setattr(
        "magent.release_evidence.documentation_drift_report", lambda root: {"ok": True}
    )
    monkeypatch.setattr("magent.release_evidence.provider_support_report", lambda: {"ok": True})

    report = build_release_evidence(
        tmp_path,
        eval_report=eval_path,
        memory_report=memory_path,
        performance_report=performance_path,
        supply_chain_report=supply_path,
        coverage_percent=72.4,
        tests="730 passed",
        ci_url="https://example.test/actions/1",
        artifacts=[artifact],
    )

    assert report["ok"] is True
    assert report["schema"] == "magent.release-evidence.v2"
    assert report["checks"]["artifacts"]["items"][0]["sha256"]


def test_release_evidence_exposes_missing_and_bad_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "magent.release_evidence.documentation_drift_report", lambda root: {"ok": True}
    )
    monkeypatch.setattr("magent.release_evidence.provider_support_report", lambda: {"ok": True})

    report = build_release_evidence(tmp_path, artifacts=["missing.whl"])

    assert report["ok"] is False
    assert {
        "evals",
        "memory",
        "performance",
        "supply_chain",
        "tests",
        "coverage",
        "ci",
        "artifacts",
    } <= set(report["blocking"])


def test_release_evidence_allows_recorded_medium_exception(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "wheel.whl"
    artifact.write_bytes(b"wheel")
    eval_path = tmp_path / "eval.json"
    eval_path.write_text('{"ok": true}', encoding="utf-8")
    memory_path = tmp_path / "memory.json"
    memory_path.write_text('{"ok": true}', encoding="utf-8")
    performance_path = tmp_path / "performance.json"
    performance_path.write_text('{"ok": true}', encoding="utf-8")
    supply_path = tmp_path / "supply.json"
    supply_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(
        "magent.release_evidence.documentation_drift_report", lambda root: {"ok": True}
    )
    monkeypatch.setattr("magent.release_evidence.provider_support_report", lambda: {"ok": True})

    report = build_release_evidence(
        tmp_path,
        eval_report=eval_path,
        memory_report=memory_path,
        performance_report=performance_path,
        supply_chain_report=supply_path,
        coverage_percent=64.9,
        coverage_required=64,
        tests="all passed",
        ci_url="https://example.test/ci",
        artifacts=[artifact],
        exceptions=["medium: roadmap coverage target deferred"],
    )

    assert report["ok"] is True
    assert report["exceptions"]
    assert report["blocking_exceptions"] == []


def test_release_evidence_atomic_writer(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "evidence.json"

    result = write_release_evidence({"ok": True}, target)

    assert result == str(target.resolve())
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    assert not target.with_suffix(".json.tmp").exists()


def test_release_evidence_cli_returns_nonzero_for_missing_proof(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["release", "evidence", "--project", str(tmp_path)])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema"] == "magent.release-evidence.v2"
    assert "evals" in payload["blocking"]
