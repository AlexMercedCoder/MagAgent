from __future__ import annotations

import json
from pathlib import Path

from magent.supply_chain import (
    build_supply_chain_evidence,
    secret_scan,
    write_supply_chain_bundle,
)


def project_fixture(root: Path) -> tuple[Path, Path]:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1"\ndependencies = ["rich>=13"]\n',
        encoding="utf-8",
    )
    artifact = root / "demo.whl"
    artifact.write_bytes(b"wheel")
    audit = root / "audit.json"
    audit.write_text(
        '{"dependencies": [{"name": "rich", "version": "13", "vulns": []}]}', encoding="utf-8"
    )
    return artifact, audit


def test_supply_chain_bundle_has_sbom_provenance_and_hashes(tmp_path: Path) -> None:
    artifact, audit = project_fixture(tmp_path)

    report = build_supply_chain_evidence(tmp_path, artifacts=[artifact], audit_report=audit)
    files = write_supply_chain_bundle(report, tmp_path / "evidence")

    assert report["ok"] is True
    assert report["sbom"]["bomFormat"] == "CycloneDX"
    assert report["provenance"]["_type"] == "https://in-toto.io/Statement/v1"
    assert report["artifacts"][0]["sha256"]
    assert all(Path(path).exists() for path in files.values())


def test_supply_chain_requires_audit_and_rejects_vulnerability(tmp_path: Path) -> None:
    artifact, audit = project_fixture(tmp_path)
    audit.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "name": "demo",
                        "version": "1",
                        "vulns": [{"id": "CVE-demo", "fix_versions": ["2"]}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    missing = build_supply_chain_evidence(tmp_path, artifacts=[artifact])
    vulnerable = build_supply_chain_evidence(tmp_path, artifacts=[artifact], audit_report=audit)

    assert missing["ok"] is False
    assert missing["dependency_audit"]["status"] == "missing"
    assert vulnerable["ok"] is False
    assert vulnerable["dependency_audit"]["vulnerabilities"][0]["id"] == "CVE-demo"


def test_supply_chain_rejects_invalid_audit_and_missing_artifact(tmp_path: Path) -> None:
    _, audit = project_fixture(tmp_path)
    audit.write_text("{", encoding="utf-8")

    report = build_supply_chain_evidence(tmp_path, artifacts=["missing.whl"], audit_report=audit)

    assert report["ok"] is False
    assert report["dependency_audit"]["status"] == "invalid"
    assert report["artifacts"][0]["error"] == "not a file"


def test_secret_scan_reports_production_secret_without_echoing_it(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "settings.py").write_text(
        'API_KEY="abcdefghijklmnopqrstuvwxyz123456"\n', encoding="utf-8"
    )

    report = secret_scan(tmp_path)

    assert report["ok"] is False
    assert report["findings"] == [{"path": "src/settings.py", "line": 1, "kind": "assigned-secret"}]
    assert "abcdefghijklmnopqrstuvwxyz" not in json.dumps(report)
