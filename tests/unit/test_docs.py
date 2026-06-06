from __future__ import annotations

from magent.docs import (
    docs_doctor,
    list_topics,
    read_topic,
    render_command_reference,
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
