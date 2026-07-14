from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from magent.cli import main as cli_main
from magent.docs import (
    docs_doctor,
    docs_root,
    list_topics,
    read_topic,
    render_command_reference,
    render_config_reference,
    render_provider_reference,
    search_docs,
)


def test_docs_topics_are_packaged():
    topics = {topic.slug for topic in list_topics()}

    assert "overview" in topics
    assert "architecture" in topics
    assert "commands" in topics
    assert "checkpoints" in topics
    assert "recipes" in topics
    assert "tutorial" in topics
    assert "testing" in topics
    assert "patch-workflow" in topics
    assert "ui" in topics
    assert "tui" in topics
    assert "context" in topics


def test_docs_search_finds_semantic_memory():
    results = search_docs("semantic memory index")

    assert results
    assert results[0]["slug"] == "semantic-memory"


def test_docs_doctor_passes_baseline():
    result = docs_doctor()

    assert result["ok"] is True
    assert read_topic("memory").startswith("# Memory")


def test_docs_doctor_checks_generated_command_reference():
    result = docs_doctor(cli_main._known_command_names())

    assert result["ok"] is True
    assert result["command_reference_current"] is True


def test_packaged_command_reference_is_current():
    expected = render_command_reference(cli_main._known_command_names())
    current = (docs_root() / "command-reference.md").read_text(encoding="utf-8")

    assert current == expected


def test_docs_generate_reference_check_command():
    result = CliRunner().invoke(cli_main.app, ["docs", "generate-reference", "--check"])

    assert result.exit_code == 0
    assert "Command reference is current" in result.output


def test_docs_generate_reference_check_detects_stale_file(tmp_path: Path):
    stale = tmp_path / "command-reference.md"
    stale.write_text("# stale\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli_main.app,
        ["docs", "generate-reference", "--check", "--out", str(stale)],
    )

    assert result.exit_code == 1
    assert "Command reference is stale" in result.output


def test_render_command_reference():
    text = render_command_reference(["ask", "memory search", "docs generate-reference"])

    assert "magent ask" in text
    assert "magent memory search" in text
    assert "magent docs generate-reference" in text


def test_render_provider_reference_uses_provider_catalog():
    text = render_provider_reference()

    assert "# Provider Reference" in text
    assert "`mistral`" in text
    assert "`deepinfra`" in text


def test_render_config_reference_uses_defaults_and_catalog():
    text = render_config_reference()

    assert "# Config Reference" in text
    assert "`defaults.provider`" in text
    assert "`balanced`" in text
    assert "`opencode-go`" in text
