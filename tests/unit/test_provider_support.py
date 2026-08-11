from __future__ import annotations

import json

from typer.testing import CliRunner

from magent.cli.main import app
from magent.provider_catalog import PROVIDER_ORDER, provider_support_report


def test_provider_support_report_is_complete_and_secret_free() -> None:
    report = provider_support_report()
    assert report["ok"] is True
    assert report["provider_count"] == len(PROVIDER_ORDER)
    assert {item["id"] for item in report["providers"]} == set(PROVIDER_ORDER)
    assert {item["support_tier"] for item in report["providers"]} <= {
        "qualified",
        "compatible",
        "experimental",
    }
    assert all(item["evidence_date"] for item in report["providers"])
    assert {"trusted-router", "prime-intellect"} <= {
        item["id"] for item in report["providers"]
    }
    nous = next(item for item in report["providers"] if item["id"] == "nous-portal")
    assert nous["live_conformance"] == "passed"
    assert nous["evidence_source"].endswith("0.50.0-nous-live-evals.json")
    serialized = json.dumps(report).lower()
    assert "sk-" not in serialized
    assert "bearer " not in serialized


def test_provider_support_report_cli_can_write_release_artifact(tmp_path) -> None:
    target = tmp_path / "provider-support.json"
    result = CliRunner().invoke(app, ["provider", "support-report", "--output", str(target)])
    assert result.exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["schema"] == "magent.provider-support.v1"
