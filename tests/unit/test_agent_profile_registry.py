from __future__ import annotations

from pathlib import Path

import pytest

from magent.agent_profiles.errors import ProfileError
from magent.agent_profiles.registry import AgentProfileRegistry


def _write(path: Path, name: str, trust: str = "managed") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\noap: '1.0'\nmetadata:\n  name: {name}\n  revision: 1\n  trust: {trust}\nspec:\n  role: {{}}\n---\n\nPrompt.\n",
        encoding="utf-8",
    )


def test_project_trust_is_derived_from_root(tmp_path: Path) -> None:
    path = tmp_path / ".magent" / "agents" / "local.md"
    _write(path, "local")
    profile = AgentProfileRegistry(tmp_path).get("local")
    assert profile is not None
    assert profile.trust == "project"
    assert "trust" not in profile.document["metadata"]


def test_magent_root_wins_over_portable_root_and_reports_shadow(tmp_path: Path) -> None:
    _write(tmp_path / ".agents" / "same.md", "same")
    _write(tmp_path / ".magent" / "agents" / "same.md", "same")
    profiles, warnings = AgentProfileRegistry(tmp_path).discover()
    assert ".magent" in str(profiles["same"].source_path)
    assert any("shadows" in warning for warning in warnings)


def test_duplicate_name_in_one_root_raises(tmp_path: Path) -> None:
    _write(tmp_path / ".agents" / "one.md", "same")
    _write(tmp_path / ".agents" / "two.yaml", "same")
    with pytest.raises(ProfileError, match="duplicate profile"):
        AgentProfileRegistry(tmp_path).discover()


def test_managed_builtins_are_oap_profiles(tmp_path: Path) -> None:
    profile = AgentProfileRegistry(tmp_path).get("review")
    assert profile is not None
    assert profile.document["oap"] == "1.0"
    assert profile.trust == "managed"


def test_default_roots_include_universal_user_directory(tmp_path: Path) -> None:
    roots = AgentProfileRegistry(tmp_path).roots()
    assert Path("~/.agentprofiles").expanduser().resolve() in {item.path for item in roots}


def test_project_precedes_native_user_and_native_user_precedes_universal(
    tmp_path: Path,
) -> None:
    class Config:
        def get(self, section: str, key: str, default=None):
            assert section == "agent_profiles"
            values = {
                "user_paths": [str(native), str(universal)],
                "project_paths": [".magent/agents", ".agents"],
            }
            return values.get(key, default)

    native = tmp_path / "native"
    universal = tmp_path / "universal"
    _write(universal / "same.md", "same")
    _write(native / "same.md", "same")
    _write(tmp_path / ".agents" / "same.md", "same")
    registry = AgentProfileRegistry(tmp_path, Config())

    profile = registry.get("same")
    assert profile is not None
    assert profile.source_path == (tmp_path / ".agents" / "same.md").resolve()
