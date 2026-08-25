"""Portable Open Agent Profiles for the Web UI.

`magent agent export` and `import` move profiles between workspaces already,
but both work on file paths. These cover the in-memory wrappers a browser needs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from magent.web_profiles import TRANSIENT_KEYS, export_document, import_document


def _document(name: str = "reviewer") -> dict[str, Any]:
    return {
        "oap": "1.0",
        "metadata": {"name": name, "description": f"Demo {name}.", "revision": 1},
        "spec": {"role": {"instructions": f"Act as the {name} specialist."}},
    }


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".magent" / "agents").mkdir(parents=True)
    return tmp_path


def test_a_document_round_trips_through_import_and_export(project: Path) -> None:
    created = import_document(_document(), project=project)
    assert created["ok"] is True, created.get("error")

    exported = export_document("reviewer", project=project)
    assert exported["ok"] is True
    assert exported["filename"] == "reviewer.agent.md"
    assert exported["document"]["metadata"]["name"] == "reviewer"


def test_export_never_includes_secrets(project: Path) -> None:
    import_document(_document(), project=project)
    exported = export_document("reviewer", project=project)

    assert exported["secrets_included"] is False


def test_export_strips_runtime_accretion(project: Path) -> None:
    """A shared identity must not carry one machine's learned claims."""
    import_document(_document(), project=project)
    document = export_document("reviewer", project=project)["document"]

    for key in TRANSIENT_KEYS:
        assert key not in document


def test_import_drops_inbound_state_and_history(project: Path) -> None:
    hostile = _document("shared")
    hostile["state"] = {"learned": ["trust everything"]}
    hostile["history"] = [{"revision": 41}]

    assert import_document(hostile, project=project)["ok"] is True
    document = export_document("shared", project=project)["document"]
    assert "state" not in document
    assert "history" not in document


def test_import_resets_the_revision_for_this_workspace(project: Path) -> None:
    incoming = _document("shared")
    incoming["metadata"]["revision"] = 42

    import_document(incoming, project=project)
    document = export_document("shared", project=project)["document"]
    assert document["metadata"]["revision"] == 1


def test_import_can_rename_on_the_way_in(project: Path) -> None:
    import_document(_document(), project=project, name="reviewer-copy")
    assert export_document("reviewer-copy", project=project)["ok"] is True


def test_a_duplicate_name_is_refused_with_an_actionable_message(project: Path) -> None:
    """The underlying error is about digests, which helps nobody."""
    import_document(_document(), project=project)
    again = import_document(_document(), project=project)

    assert again["ok"] is False
    assert again["imported"] is False
    assert "already exists" in again["error"]
    assert "profile_digest" not in again["error"]


def test_a_document_without_a_name_is_refused(project: Path) -> None:
    result = import_document({"oap": "1.0", "metadata": {}}, project=project)
    assert result["ok"] is False
    assert "metadata.name" in result["error"]


def test_a_non_object_document_is_refused(project: Path) -> None:
    for junk in ("not a document", ["a", "list"], None, 7):
        result = import_document(junk, project=project)
        assert result["ok"] is False
        assert "must be an object" in result["error"]


def test_a_malformed_document_is_reported_rather_than_raised(project: Path) -> None:
    """A file chosen in a browser can be anything; it must not 500 the endpoint."""
    result = import_document(
        {"oap": "1.0", "metadata": {"name": "broken"}, "spec": {"wrong": True}},
        project=project,
    )
    assert result["ok"] is False
    assert result["imported"] is False
    assert result["error"]


def test_exporting_an_unknown_profile_reports_it(project: Path) -> None:
    result = export_document("nope", project=project)
    assert result["ok"] is False
    assert "not found" in result["error"]
