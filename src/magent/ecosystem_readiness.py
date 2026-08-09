"""Generated, credential-free readiness evidence for the local Mag ecosystem."""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent import __version__
from magent.desktop_api import platform_contracts
from magent.docs import docs_doctor
from magent.provider_catalog import provider_support_report


def ecosystem_readiness(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    workspace = root_path.parent if root_path.name.lower() == "magagent" else root_path
    graph_root = workspace / "MagGraph"
    desktop_root = workspace / "MagCommandCenter"
    checks = [
        _check("magent-contracts", platform_contracts().get("ok", False), "magent.platform-contracts.v1"),
        _check("provider-catalog", provider_support_report().get("ok", False), "magent.provider-support.v1; live tests separate"),
        _check("packaged-docs", docs_doctor().get("ok", False), "required built-in topics"),
        _maggraph_check(graph_root),
        _desktop_check(desktop_root),
    ]
    local_ok = all(check["ok"] for check in checks)
    return {
        "schema": "mag.ecosystem-readiness.v1",
        "ok": local_ok,
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace": str(workspace),
        "components": {
            "magagent": {"version": __version__, "contracts": platform_contracts()["contracts"]},
            "maggraph": _maggraph_metadata(graph_root),
            "command_center": _desktop_metadata(desktop_root),
        },
        "checks": checks,
        "external_gates": [
            "maintainer-run live provider completion and tool-use matrix",
            "signed and notarized macOS/Windows packages",
            "manual keyboard and screen-reader checks on macOS, Windows, and Linux",
            "four simultaneous packaged desktop tasks on release hardware",
            "official MCP conformance for stable upstream extension surfaces",
            "hosted plugin registry signing and security-scan infrastructure",
        ],
        "policy": "ok covers deterministic local contracts only; external gates remain mandatory for a 1.0 release claim",
    }


def write_ecosystem_report(report: dict[str, Any], output: str | Path) -> Path:
    target = Path(output).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return target


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "status": "passed" if ok else "failed", "detail": detail}


def _maggraph_check(root: Path) -> dict[str, Any]:
    metadata = _maggraph_metadata(root)
    benchmark = root / "planning" / "benchmark-baseline.json"
    ok = bool(metadata.get("version") and metadata.get("contracts"))
    detail = "installed graph contract"
    if benchmark.exists():
        detail += " with source benchmark baseline"
    return _check("maggraph-contract", ok, detail)


def _maggraph_metadata(root: Path) -> dict[str, Any]:
    cargo = root / "Cargo.toml"
    if not cargo.exists():
        try:
            import maggraph

            graph_index = getattr(maggraph, "GraphIndex", object)
            capabilities = [
                name
                for name in ("hybrid_search", "recall_bundle", "apply_memory_batch")
                if hasattr(graph_index, name)
            ]
            return {
                "available": True,
                "source_checkout": False,
                "version": getattr(maggraph, "__version__", "unknown"),
                "contracts": capabilities,
            }
        except ImportError:
            return {"available": False, "path": str(root)}
    try:
        data = tomllib.loads(cargo.read_text(encoding="utf-8"))
        version = data.get("workspace", {}).get("package", {}).get("version", "")
    except (OSError, tomllib.TOMLDecodeError):
        version = ""
    return {
        "available": True,
        "source_checkout": True,
        "path": str(root),
        "version": version,
        "contracts": ["hybrid-search", "recall-bundle", "reviewed-batch", "batch-recovery", "benchmark-report-v1"],
    }


def _desktop_check(root: Path) -> dict[str, Any]:
    metadata = _desktop_metadata(root)
    if not metadata.get("available"):
        return {"name": "command-center-contract", "ok": True, "status": "skipped", "detail": "desktop source checkout not supplied to CLI"}
    return _check("command-center-contract", bool(metadata.get("version")), "package metadata and typed task client")


def _desktop_metadata(root: Path) -> dict[str, Any]:
    package = root / "package.json"
    if not package.exists():
        return {"available": False, "path": str(root)}
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return {
        "available": True,
        "path": str(root),
        "version": data.get("version", ""),
        "contracts": ["magent.task.v1", "magent.task-event.v1", "mag-command-center.performance.v1"],
    }
