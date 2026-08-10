"""Regression corpus for identifier-to-path conversion.

Memory node ids, plugin names and state keys, database and user names and
artifact paths were each sanitised differently, or not at all. Every hostile
shape belongs here once, so a new conversion site can be checked against it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from magent.safe_names import (
    InvalidNameError,
    contained_path,
    is_safe_component,
    safe_component,
    slugify_component,
    unslugify_component,
)

# Shapes that must never survive into a path component.
HOSTILE = [
    "../etc/passwd",
    "..",
    ".",
    "../../..",
    "/etc/passwd",
    "a/b",
    "a\\b",
    "foo/../bar",
    "  ../x  ",
    "\x00null",
    "name\nnewline",
    "name;rm -rf /",
    "name|pipe",
    "name with spaces",
    "~/.ssh/id_rsa",
    "$(whoami)",
    "`whoami`",
    "con",
    "COM1",
    "nul.txt",
    "-leading-dash",
]

BENIGN = ["users", "session_summary", "node-123", "a.b.c", "Project_2026", "x"]


class TestSlugify:
    @pytest.mark.parametrize("value", HOSTILE)
    def test_hostile_values_become_single_safe_components(self, value: str) -> None:
        slug = slugify_component(value)
        assert slug, "slugify must always produce something usable"
        assert "/" not in slug
        assert "\\" not in slug
        assert slug not in {".", ".."}
        assert not slug.startswith("-")
        # A slug is only useful if it stays put when joined to a root.
        root = Path("/tmp/magent-root").resolve()
        assert root in (root / slug).resolve(strict=False).parents or (root / slug).resolve(
            strict=False
        ) == root

    @pytest.mark.parametrize("value", BENIGN)
    def test_benign_values_are_untouched(self, value: str) -> None:
        # Existing on-disk data must keep resolving to the same filename.
        assert slugify_component(value) == value

    def test_empty_and_none_use_the_fallback(self) -> None:
        assert slugify_component("") == "unnamed"
        assert slugify_component(None) == "unnamed"
        assert slugify_component("   ", fallback="fb") == "fb"

    def test_round_trip_recovers_the_original(self) -> None:
        # Exact for values that need no safety prefix. A leading dot or dash
        # gets an underscore so the component cannot be read as traversal or as
        # a command flag, and that prefix is deliberately not reversible.
        for value in ("a/b", "name with spaces", "a:b"):
            assert unslugify_component(slugify_component(value)) == value

        assert unslugify_component(slugify_component("../x")).endswith("../x")


class TestSafeComponent:
    @pytest.mark.parametrize("value", HOSTILE)
    def test_hostile_values_are_rejected(self, value: str) -> None:
        assert not is_safe_component(value)
        with pytest.raises(InvalidNameError):
            safe_component(value)

    @pytest.mark.parametrize("value", BENIGN)
    def test_benign_values_are_accepted(self, value: str) -> None:
        assert safe_component(value) == value

    def test_length_is_bounded(self) -> None:
        assert not is_safe_component("a" * 200)
        assert len(slugify_component("a" * 500)) <= 128


class TestContainedPath:
    def test_joins_under_the_root(self, tmp_path: Path) -> None:
        assert contained_path(tmp_path, "users", "alice.json").parent.name == "users"

    @pytest.mark.parametrize("value", ["../escape", "/etc/passwd", ".."])
    def test_refuses_to_escape(self, tmp_path: Path, value: str) -> None:
        with pytest.raises(InvalidNameError):
            contained_path(tmp_path, value)

    def test_lossy_mode_contains_rather_than_rejects(self, tmp_path: Path) -> None:
        result = contained_path(tmp_path, "../escape", strict=False)
        assert tmp_path.resolve() in result.parents


class TestCallSitesUseTheHelper:
    def test_database_paths_sanitise_user_and_name(self, tmp_path: Path, monkeypatch) -> None:
        """`db_name` was sanitised but `username` was not, though both are path
        components."""
        import magent.tools.db as db_module

        monkeypatch.setattr(db_module, "USERS_DIR", tmp_path)
        path = db_module._db_path("../evil", "../also-evil")

        assert tmp_path.resolve() in path.resolve().parents
        assert ".." not in path.parts

    def test_memory_node_ids_cannot_escape(self) -> None:
        assert "/" not in slugify_component("../../../etc/passwd")
