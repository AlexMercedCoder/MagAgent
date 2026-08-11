from __future__ import annotations

import json

from typer.testing import CliRunner

from magent.cli.main import app
from magent.security_assurance import security_assurance_report


def test_security_assurance_probes_pass() -> None:
    report = security_assurance_report()

    assert report["ok"] is True
    assert report["schema"] == "magent.security-assurance.v1"
    assert {item["key"] for item in report["checks"]} == {
        "command-policy",
        "network-policy",
        "path-containment",
        "gateway-default",
        "atomic-persistence",
    }


def test_security_report_cli_writes_sanitized_json(tmp_path) -> None:
    output = tmp_path / "security.json"
    result = CliRunner().invoke(app, ["system", "security-report", "-o", str(output)])

    assert result.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["ok"] is True
    serialized = output.read_text(encoding="utf-8").lower()
    assert "api_key" not in serialized
    assert "bearer " not in serialized
