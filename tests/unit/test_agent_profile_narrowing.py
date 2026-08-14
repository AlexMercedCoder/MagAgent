from __future__ import annotations

from magent.agent_profiles.digest import digest_document, digest_spec
from magent.agent_profiles.effective import narrow_permission_mode, resolve_effective_profile
from magent.agent_profiles.models import ResolvedProfile
from magent.config import DEFAULT_GLOBAL_CONFIG, Config


def _profile(spec: dict) -> ResolvedProfile:
    document = {"oap": "1.0", "metadata": {"name": "test", "revision": 1}, "spec": {"role": {}, **spec}, "state": []}
    return ResolvedProfile(document, None, "managed", digest_spec(document), digest_document(document))


def _config() -> Config:
    raw = {**DEFAULT_GLOBAL_CONFIG, "defaults": {**DEFAULT_GLOBAL_CONFIG["defaults"], "permission_mode": "balanced"}, "agent": {**DEFAULT_GLOBAL_CONFIG["agent"], "max_model_rounds_per_turn": 8}}
    return Config(raw)


def test_profile_cannot_widen_permission_mode() -> None:
    effective = resolve_effective_profile(_profile({"permissions": {"default": "yolo"}}), _config(), {"read_file"})
    assert effective.permission_mode == "balanced"
    assert any(item.field == "permissions.default" for item in effective.adjustments)


def test_profile_cannot_add_a_tool_config_disabled() -> None:
    effective = resolve_effective_profile(_profile({"tools": {"allow": ["read_file", "run_shell"]}}), _config(), {"read_file"})
    assert effective.tools == {"read_file"}
    assert "run_shell" not in effective.tools


def test_profile_cannot_raise_the_turn_budget() -> None:
    effective = resolve_effective_profile(_profile({"runtime": {"max_turns": 100}}), _config(), {"read_file"})
    assert effective.max_turns == 8
    assert any(item.field == "runtime.max_turns" for item in effective.adjustments)


def test_permission_mode_rounding_goes_down() -> None:
    assert narrow_permission_mode("balanced", "silent") == "balanced"
    assert narrow_permission_mode("silent", "paranoid") == "paranoid"


def test_every_narrowing_produces_an_adjustment() -> None:
    effective = resolve_effective_profile(_profile({"permissions": {"default": "yolo"}, "runtime": {"max_turns": 50}}), _config(), {"read_file"})
    assert {item.field for item in effective.adjustments} >= {"permissions.default", "runtime.max_turns"}
