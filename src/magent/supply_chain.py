"""Deterministic SBOM, provenance, artifact hash, and secret-scan evidence."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

from magent import __version__
from magent.workbench_store import now_iso

SCHEMA = "magent.supply-chain.v1"
SBOM_SCHEMA = "CycloneDX"


def build_supply_chain_evidence(
    root: str | Path = ".",
    *,
    artifacts: list[str | Path] | None = None,
    audit_report: str | Path | None = None,
) -> dict[str, Any]:
    project = Path(root).resolve()
    artifact_items = [_artifact(project, item) for item in artifacts or []]
    audit = _dependency_audit(audit_report)
    secrets = secret_scan(project)
    sbom = build_sbom(project)
    provenance = build_provenance(project, artifact_items)
    checks = {
        "artifacts": bool(artifact_items) and all(item["ok"] for item in artifact_items),
        "dependency_audit": audit["ok"],
        "secret_scan": secrets["ok"],
        "sbom": bool(sbom["components"]),
        "provenance": bool(provenance["subject"]),
    }
    return {
        "ok": all(checks.values()),
        "schema": SCHEMA,
        "version": __version__,
        "generated_at": now_iso(),
        "checks": checks,
        "artifacts": artifact_items,
        "dependency_audit": audit,
        "secret_scan": secrets,
        "sbom": sbom,
        "provenance": provenance,
        "signing": {
            "status": "external",
            "detail": "Tag and artifact signing require maintainer-managed signing credentials.",
        },
    }


def write_supply_chain_bundle(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / "supply-chain.json"
    sbom_path = directory / "sbom.cdx.json"
    provenance_path = directory / "provenance.intoto.jsonl"
    checksums_path = directory / "SHA256SUMS"
    _write_json(report_path, report)
    _write_json(sbom_path, report["sbom"])
    provenance_path.write_text(
        json.dumps(report["provenance"], separators=(",", ":")) + "\n", encoding="utf-8"
    )
    checksums_path.write_text(
        "".join(
            f"{item['sha256']}  {Path(item['path']).name}\n"
            for item in report["artifacts"]
            if item["ok"]
        ),
        encoding="utf-8",
    )
    return {
        "report": str(report_path),
        "sbom": str(sbom_path),
        "provenance": str(provenance_path),
        "checksums": str(checksums_path),
    }


def build_sbom(root: str | Path) -> dict[str, Any]:
    project = Path(root).resolve()
    dependencies = _declared_dependencies(project)
    components = []
    for name in dependencies:
        try:
            distribution = metadata.distribution(name)
            version = distribution.version
            license_name = distribution.metadata.get("License", "")
        except metadata.PackageNotFoundError:
            version = "not-installed"
            license_name = ""
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "licenses": ([{"license": {"name": license_name}}] if license_name else []),
                "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
            }
        )
    return {
        "bomFormat": SBOM_SCHEMA,
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{_deterministic_id(project)}",
        "version": 1,
        "metadata": {
            "timestamp": now_iso(),
            "component": {
                "type": "application",
                "name": "mag-agent",
                "version": __version__,
                "purl": f"pkg:pypi/mag-agent@{__version__}",
            },
        },
        "components": components,
    }


def build_provenance(root: str | Path, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    project = Path(root).resolve()
    commit = _git(project, "rev-parse", "HEAD")
    remote = _git(project, "remote", "get-url", "origin")
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": Path(item["path"]).name, "digest": {"sha256": item["sha256"]}}
            for item in artifacts
            if item["ok"]
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://pypa.io/build",
                "externalParameters": {"version": __version__},
                "internalParameters": {
                    "python": platform.python_version(),
                    "implementation": platform.python_implementation(),
                },
                "resolvedDependencies": [
                    {"uri": remote, "digest": {"gitCommit": commit}} if remote else {}
                ],
            },
            "runDetails": {
                "builder": {"id": "https://github.com/AlexMercedCoder/MagAgent/actions"},
                "metadata": {"invocationId": commit, "startedOn": now_iso()},
            },
        },
    }


def secret_scan(root: str | Path) -> dict[str, Any]:
    project = Path(root).resolve()
    findings: list[dict[str, Any]] = []
    patterns = (
        ("private-key", re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY")),
        ("provider-key", re.compile(r"sk-[A-Za-z0-9_-]{24,}")),
        (
            "assigned-secret",
            re.compile(
                r"(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|PASSWORD)\s*=\s*[\"']?"
                r"(?!xxx|test|fake|placeholder|your-)[A-Za-z0-9_./+-]{24,}",
                re.IGNORECASE,
            ),
        ),
    )
    for relative in _tracked_files(project):
        if relative.parts and relative.parts[0] in {"tests", "dist", "build"}:
            continue
        path = project / relative
        try:
            if path.stat().st_size > 5_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in patterns:
                if pattern.search(line):
                    findings.append(
                        {"path": relative.as_posix(), "line": line_number, "kind": kind}
                    )
    return {
        "ok": not findings,
        "files_scanned": len(_tracked_files(project)),
        "findings": findings,
    }


def _dependency_audit(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"ok": False, "status": "missing", "vulnerabilities": []}
    source = Path(path).resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "invalid", "error": str(exc), "vulnerabilities": []}
    dependencies = value.get("dependencies", value if isinstance(value, list) else [])
    vulnerabilities = []
    for dependency in dependencies if isinstance(dependencies, list) else []:
        for vulnerability in dependency.get("vulns", []):
            vulnerabilities.append(
                {
                    "dependency": dependency.get("name", ""),
                    "version": dependency.get("version", ""),
                    "id": vulnerability.get("id", ""),
                    "fix_versions": vulnerability.get("fix_versions", []),
                }
            )
    return {
        "ok": not vulnerabilities,
        "status": "passed" if not vulnerabilities else "vulnerable",
        "path": str(source),
        "sha256": _sha256(source),
        "vulnerabilities": vulnerabilities,
    }


def _declared_dependencies(root: Path) -> list[str]:
    project_file = root / "pyproject.toml"
    if not project_file.exists():
        return [item.metadata["Name"] for item in metadata.distributions() if item.metadata["Name"]]
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    names = []
    for requirement in project.get("dependencies", []):
        name = re.split(r"[<>=!~;\[\s]", str(requirement), maxsplit=1)[0]
        if name:
            names.append(name)
    return sorted(set(names), key=str.lower)


def _tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, timeout=20, check=False
    )
    if completed.returncode == 0:
        return [Path(item.decode()) for item in completed.stdout.split(b"\0") if item]
    return [path.relative_to(root) for path in root.rglob("*") if path.is_file()]


def _artifact(root: Path, value: str | Path) -> dict[str, Any]:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_file():
        return {"path": str(path), "ok": False, "error": "not a file"}
    return {"path": str(path), "ok": True, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, timeout=20, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _deterministic_id(root: Path) -> str:
    digest = hashlib.sha256(
        f"mag-agent:{__version__}:{_git(root, 'rev-parse', 'HEAD')}".encode()
    ).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
