from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent.cli.main import app

runner = CliRunner()


def test_profile_cli_create_list_show_validate_and_digest(tmp_path: Path) -> None:
    created = runner.invoke(
        app, ["agent", "create", "reviewer", "--project", str(tmp_path), "--prompt", "Review."]
    )
    listed = runner.invoke(app, ["agent", "list", "--project", str(tmp_path)])
    shown = runner.invoke(app, ["agent", "show", "reviewer", "--project", str(tmp_path)])
    path = tmp_path / ".magent" / "agents" / "reviewer.md"
    validated = runner.invoke(app, ["agent", "validate", str(path)])
    digested = runner.invoke(app, ["agent", "digest", "reviewer", "--project", str(tmp_path)])
    assert all(result.exit_code == 0 for result in (created, listed, shown, validated, digested))
    assert json.loads(shown.output)["profile"]["document"]["oap"] == "1.0"
    assert json.loads(digested.output)["spec_digest"].startswith("sha256:")


def test_convert_is_preview_only_without_write_flag(tmp_path: Path) -> None:
    path = tmp_path / "legacy.md"
    original = "---\ndescription: Old\n---\nLegacy prompt.\n"
    path.write_text(original, encoding="utf-8")
    preview = runner.invoke(app, ["agent", "convert", str(path)])
    assert preview.exit_code == 0
    assert "oap: '1.0'" in preview.output
    assert path.read_text(encoding="utf-8") == original
    assert not path.with_suffix(".md.legacy.bak").exists()


def test_agent_conformance_command() -> None:
    result = runner.invoke(app, ["agent", "conformance"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["level"] == 3
    assert payload["passed"] == payload["total"]
