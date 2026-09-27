"""G-9: `magent provider ping` (one tiny completion)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from magent.cli import main as cli_main
from magent.provider_catalog import PROVIDER_SUPPORT
from magent.provider_ping import MAX_TOKENS_LIMIT, append_record, ping_provider
from tests.unit.test_cli import redirect_config


def test_ping_uses_at_most_16_tokens_and_reports_usage(monkeypatch, tmp_path: Path) -> None:
    from magent.config import Config

    seen: dict = {}

    async def fake_completion(**kwargs):
        from types import SimpleNamespace

        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="OK"))],
            usage=SimpleNamespace(prompt_tokens=9, completion_tokens=1),
        )

    monkeypatch.setattr("litellm.acompletion", fake_completion)
    result = ping_provider(Config({}, {}), "mock", "offline-demo", max_tokens=500)
    assert result["ok"] is True and result["reply"] == "OK"
    assert seen["max_tokens"] == MAX_TOKENS_LIMIT == 16
    report = tmp_path / "report.json"
    append_record(report, result)
    append_record(report, result)
    assert len(json.loads(report.read_text())["checks"]) == 2


def test_ping_cli_reports_failures_with_a_next_step(monkeypatch, tmp_path: Path) -> None:
    redirect_config(monkeypatch, tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "alex"]).exit_code == 0
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    failed = runner.invoke(cli_main.app, ["provider", "ping", "openai"])
    assert failed.exit_code == 1 and "magent auth list" in failed.output
    ok = runner.invoke(cli_main.app, ["provider", "ping", "mock", "--json"])
    assert ok.exit_code == 0, ok.output
    payload, _end = json.JSONDecoder().raw_decode(ok.output[ok.output.index("{") :])
    assert payload["ok"] is True


def test_pinged_providers_keep_their_tier_and_cite_the_report() -> None:
    for provider in ("openai", "anthropic"):
        support = PROVIDER_SUPPORT[provider]
        assert support["tier"] == "compatible"
        assert support["evidence_source"].endswith("2026-09-27-provider-connectivity.json")
        assert Path(__file__).resolve().parents[2].joinpath(support["evidence_source"]).exists()
