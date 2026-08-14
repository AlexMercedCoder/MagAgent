from __future__ import annotations

import json
from pathlib import Path

import pytest

from magent.agent_profiles.digest import digest_document, digest_spec
from magent.agent_profiles.documents import parse_document, validate_document
from magent.agent_profiles.errors import ProfileValidationError
from magent.agent_profiles.registry import AgentProfileRegistry


def _document(name: str = "reviewer") -> dict:
    return {
        "oap": "1.0",
        "metadata": {"name": name, "revision": 1},
        "spec": {"role": {"instructions": "Review carefully."}},
        "state": [],
    }


def test_oap_yaml_json_and_markdown_encodings(tmp_path: Path) -> None:
    document = _document()
    yaml_path = tmp_path / "one.yaml"
    yaml_path.write_text("oap: '1.0'\nmetadata:\n  name: reviewer\n  revision: 1\nspec:\n  role:\n    instructions: Review.\n", encoding="utf-8")
    json_path = tmp_path / "two.json"
    json_path.write_text(json.dumps(document), encoding="utf-8")
    md_path = tmp_path / "three.md"
    md_path.write_text("---\noap: '1.0'\nmetadata:\n  name: reviewer\n  revision: 1\nspec:\n  role: {}\n---\n\nReview from Markdown.\n", encoding="utf-8")

    for path in (yaml_path, json_path, md_path):
        loaded, _body, _encoding = parse_document(path)
        validate_document(loaded)
        assert loaded["metadata"]["name"] == "reviewer"
    assert parse_document(md_path)[0]["spec"]["role"]["instructions"] == "Review from Markdown."


def test_yaml_timestamp_is_kept_as_string(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text("oap: '1.0'\nmetadata:\n  name: x\n  revision: 1\n  created: 2026-08-14T10:00:00Z\nspec:\n  role: {}\n", encoding="utf-8")
    document, _body, _encoding = parse_document(path)
    assert document["metadata"]["created"] == "2026-08-14T10:00:00Z"


def test_invalid_profile_reports_json_pointer() -> None:
    with pytest.raises(ProfileValidationError, match="/metadata"):
        validate_document({"oap": "1.0", "metadata": {}, "spec": {"role": {}}})


def test_digests_are_canonical_and_spec_digest_ignores_state() -> None:
    first = _document()
    second = json.loads(json.dumps(first))
    second["state"] = [{"id": "fact", "content": "learned"}]
    assert digest_document(first) != digest_document(second)
    assert digest_spec(first) == digest_spec(second)


def test_legacy_load_is_in_memory_and_does_not_modify_file(tmp_path: Path) -> None:
    path = tmp_path / "reviewer.md"
    original = "---\npermissionMode: paranoid\ncustom: preserved\n---\nReview.\n"
    path.write_text(original, encoding="utf-8")
    profile = AgentProfileRegistry(tmp_path).load_path(path)
    assert profile.legacy is True
    assert profile.document["metadata"]["annotations"]["magagent.dev/legacy"]["custom"] == "preserved"
    assert path.read_text(encoding="utf-8") == original
