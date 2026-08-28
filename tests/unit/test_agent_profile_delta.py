from __future__ import annotations

from pathlib import Path

import pytest

from magent.agent_profiles.delta import (
    apply_delta,
    make_delta,
    rebase_delta,
    restore_checkpoint,
)
from magent.agent_profiles.documents import atomic_write, parse_document, render_document
from magent.agent_profiles.errors import ProfileConflictError, ProfileError
from magent.agent_profiles.registry import AgentProfileRegistry


def _profile(tmp_path: Path):
    path = tmp_path / "reviewer.md"
    path.write_text(
        "---\noap: '1.0'\nmetadata:\n  name: reviewer\n  revision: 1\nspec:\n  role: {}\nstate: []\nhistory: []\n---\n\nReview.\n",
        encoding="utf-8",
    )
    return path, AgentProfileRegistry(tmp_path).load_path(path)


def test_delta_writes_state_and_bumps_revision_exactly_once(tmp_path: Path) -> None:
    path, profile = _profile(tmp_path)
    delta = make_delta(
        profile,
        [
            {
                "op": "add",
                "path": "/state/-",
                "value": {"id": "style", "content": "Skip formatter findings"},
            }
        ],
    )
    result = apply_delta(path, delta)
    reloaded = AgentProfileRegistry(tmp_path).load_path(path)
    assert result["revision"] == 2
    assert reloaded.revision == 2
    assert reloaded.document["state"][0]["id"] == "style"


def test_operation_targeting_spec_is_rejected() -> None:
    class P:
        name = "x"
        source_path = None
        revision = 1
        profile_digest = "sha256:x"

    with pytest.raises(ProfileError, match="outside /state"):
        make_delta(P(), [{"op": "replace", "path": "/spec/tools", "value": {}}])


def test_delta_secret_is_scrubbed_before_disk(tmp_path: Path) -> None:
    path, profile = _profile(tmp_path)
    delta = make_delta(
        profile,
        [
            {
                "op": "add",
                "path": "/state/-",
                "value": {"id": "bad", "content": "key sk-abcdefghijklmnop1234"},
            }
        ],
    )
    apply_delta(path, delta)
    assert "sk-abcdefghijklmnop1234" not in path.read_text(encoding="utf-8")


def test_stale_revision_is_rejected_without_modifying_file(tmp_path: Path) -> None:
    path, profile = _profile(tmp_path)
    delta = make_delta(
        profile, [{"op": "add", "path": "/state/-", "value": {"id": "a", "content": "A"}}]
    )
    first = make_delta(
        profile, [{"op": "add", "path": "/state/-", "value": {"id": "b", "content": "B"}}]
    )
    apply_delta(path, first)
    before = path.read_bytes()
    with pytest.raises(ProfileConflictError):
        apply_delta(path, delta)
    assert path.read_bytes() == before


def test_checkpoint_restores_previous_revision(tmp_path: Path) -> None:
    path, profile = _profile(tmp_path)
    delta = make_delta(
        profile, [{"op": "add", "path": "/state/-", "value": {"id": "a", "content": "A"}}]
    )
    result = apply_delta(path, delta)
    assert AgentProfileRegistry(tmp_path).load_path(path).revision == 2
    restored = restore_checkpoint(path, Path(result["checkpoint"]))
    assert restored["revision"] == 1
    assert AgentProfileRegistry(tmp_path).load_path(path).document["state"] == []


def test_canonical_delta_rejects_rebase_without_private_snapshot(tmp_path: Path) -> None:
    path, profile = _profile(tmp_path)
    delta = make_delta(
        profile,
        [
            {
                "op": "replace",
                "path": "/state/target",
                "value": {"id": "target", "content": "new"},
            }
        ],
    )
    document, _body, encoding = parse_document(path)
    document.setdefault("state", []).append({"id": "other", "content": "changed"})
    document["metadata"]["revision"] = 2
    atomic_write(path, render_document(document, encoding))

    with pytest.raises(ProfileConflictError, match="regenerate"):
        rebase_delta(path, delta)
    with pytest.raises(ProfileConflictError, match="regenerate"):
        apply_delta(path, delta, auto_rebase=True)


def test_rebase_rejects_targeted_state_conflict(tmp_path: Path) -> None:
    path, profile = _profile(tmp_path)
    delta = make_delta(
        profile,
        [
            {
                "op": "replace",
                "path": "/state/target",
                "value": {"id": "target", "content": "new"},
            }
        ],
    )
    document, _body, encoding = parse_document(path)
    document.setdefault("state", []).append({"id": "target", "content": "concurrent"})
    document["metadata"]["revision"] = 2
    atomic_write(path, render_document(document, encoding))

    with pytest.raises(ProfileConflictError, match="regenerate"):
        apply_delta(path, delta, auto_rebase=True)
