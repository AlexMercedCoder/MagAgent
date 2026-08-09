from __future__ import annotations

import json

from typer.testing import CliRunner

from magent.cli.main import app
from magent.ecosystem_readiness import ecosystem_readiness


def workspace(tmp_path):
    agent = tmp_path / "MagAgent"
    graph = tmp_path / "MagGraph"
    desktop = tmp_path / "MagCommandCenter"
    agent.mkdir()
    (graph / "planning").mkdir(parents=True)
    desktop.mkdir()
    (graph / "Cargo.toml").write_text('[workspace.package]\nversion = "0.3.0"\n', encoding="utf-8")
    (graph / "planning" / "benchmark-baseline.json").write_text("{}\n", encoding="utf-8")
    (desktop / "package.json").write_text('{"version":"0.2.0"}\n', encoding="utf-8")
    return agent


def test_ecosystem_report_separates_local_checks_from_external_gates(tmp_path) -> None:
    report = ecosystem_readiness(workspace(tmp_path))
    assert report["schema"] == "mag.ecosystem-readiness.v1"
    assert report["ok"] is True
    assert report["components"]["maggraph"]["version"] == "0.3.0"
    assert report["components"]["command_center"]["version"] == "0.2.0"
    assert "signed and notarized macOS/Windows packages" in report["external_gates"]
    assert "four simultaneous packaged desktop tasks on release hardware" in report["external_gates"]


def test_ecosystem_report_cli_writes_json(tmp_path) -> None:
    agent = workspace(tmp_path)
    output = tmp_path / "readiness.json"
    result = CliRunner().invoke(app, ["system", "ecosystem-report", "--root", str(agent), "--output", str(output)])
    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == "mag.ecosystem-readiness.v1"
