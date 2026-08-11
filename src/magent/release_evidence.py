"""Machine-readable evidence bundle for release qualification."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from magent import __version__
from magent.docs import documentation_drift_report
from magent.provider_catalog import provider_support_report
from magent.security_assurance import security_assurance_report
from magent.workbench_store import now_iso

SCHEMA = "magent.release-evidence.v1"


def build_release_evidence(
    root: str | Path = ".",
    *,
    eval_report: str | Path | None = None,
    memory_report: str | Path | None = None,
    performance_report: str | Path | None = None,
    coverage_percent: float | None = None,
    coverage_required: float = 70.0,
    tests: str = "",
    ci_url: str = "",
    artifacts: list[str | Path] | None = None,
    exceptions: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic release evidence report without making network requests."""
    project = Path(root).resolve()
    eval_data = _read_json(eval_report) if eval_report else None
    eval_evidence = _eval_evidence(eval_report, eval_data) if eval_report and eval_data else None
    memory_data = _read_json(memory_report) if memory_report else None
    performance_data = _read_json(performance_report) if performance_report else None
    artifact_data = [_artifact(project, item) for item in artifacts or []]
    git = _git_evidence(project)
    checks = {
        "docs": documentation_drift_report(project),
        "providers": provider_support_report(),
        "security": security_assurance_report(),
        "evals": {
            "ok": bool(eval_data and eval_data.get("ok")),
            "status": "recorded" if eval_data else "missing",
            "report": eval_evidence,
        },
        "memory": _report_check(memory_report, memory_data),
        "performance": _report_check(performance_report, performance_data),
        "tests": {"ok": bool(tests), "status": tests or "missing"},
        "coverage": {
            "ok": coverage_percent is not None and coverage_percent >= coverage_required,
            "percent": coverage_percent,
            "required": coverage_required,
        },
        "ci": {"ok": bool(ci_url), "url": ci_url, "status": "recorded" if ci_url else "missing"},
        "artifacts": {
            "ok": bool(artifact_data) and all(item["ok"] for item in artifact_data),
            "items": artifact_data,
        },
    }
    blocking = [name for name, result in checks.items() if not result.get("ok")]
    release_exceptions = list(exceptions or [])
    blocking_exceptions = [
        item
        for item in release_exceptions
        if item.strip().lower().startswith(("critical:", "high:"))
    ]
    return {
        "ok": not blocking and not blocking_exceptions,
        "schema": SCHEMA,
        "version": __version__,
        "generated_at": now_iso(),
        "root": str(project),
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "git": git,
        "checks": checks,
        "blocking": blocking,
        "exceptions": release_exceptions,
        "blocking_exceptions": blocking_exceptions,
    }


def write_release_evidence(report: dict[str, Any], path: str | Path) -> str:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(target)
    return str(target)


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).resolve().read_text(encoding="utf-8"))


def _eval_evidence(path: str | Path, report: dict[str, Any]) -> dict[str, Any]:
    source = Path(path).resolve()
    keys = (
        "schema",
        "suite",
        "version",
        "ran_at",
        "passed",
        "total",
        "success_rate",
        "artifact_passed",
        "artifact_total",
        "artifact_success_rate",
        "targets",
        "metrics",
    )
    return {
        "path": str(source),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "summary": {key: report.get(key) for key in keys if key in report},
    }


def _report_check(
    path: str | Path | None,
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not path or not report:
        return {"ok": False, "status": "missing", "report": None}
    source = Path(path).resolve()
    return {
        "ok": bool(report.get("ok")),
        "status": "recorded",
        "report": {
            "path": str(source),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "schema": report.get("schema"),
            "metrics": report.get("metrics", {}),
            "gates": report.get("gates", {}),
        },
    }


def _artifact(root: Path, value: str | Path) -> dict[str, Any]:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_file():
        return {"path": str(path), "ok": False, "error": "not a file"}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "ok": True, "bytes": path.stat().st_size, "sha256": digest}


def _git_evidence(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=10, check=False
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    status = run("status", "--short")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "tag": run("describe", "--tags", "--exact-match"),
        "clean": not status,
        "status": status.splitlines(),
    }
