from __future__ import annotations

import pytest

import magent.permissions as permissions
from magent.permissions import RiskTier, check_permission


@pytest.mark.parametrize("mode", ["silent", "balanced", "paranoid", "unknown"])
def test_permission_gate_auto_approves_silent_actions(mode: str) -> None:
    result = check_permission("Read file", RiskTier.SILENT, mode=mode, interactive=False)
    assert result.approved is True
    assert result.reason == "auto"


def test_permission_gate_noninteractive_requires_approval() -> None:
    result = check_permission(
        "Run command",
        RiskTier.CONFIRM,
        mode="balanced",
        interactive=False,
    )
    assert result.approved is False
    assert result.reason == "permission-required"


@pytest.mark.parametrize(("answer", "approved"), [(True, True), (False, False)])
def test_permission_gate_confirmation_prompt(monkeypatch, answer: bool, approved: bool) -> None:
    monkeypatch.setattr(permissions.Confirm, "ask", lambda *_args, **_kwargs: answer)
    result = check_permission("Run tests", RiskTier.CONFIRM, interactive=True)
    assert result.approved is approved
    assert result.reason == ("user-confirmed" if approved else "user-denied")


@pytest.mark.parametrize(("answer", "approved"), [("yes", True), ("no", False)])
def test_permission_gate_block_prompt(monkeypatch, answer: str, approved: bool) -> None:
    monkeypatch.setattr(permissions.Prompt, "ask", lambda *_args, **_kwargs: answer)
    result = check_permission("Delete data", RiskTier.BLOCK, interactive=True)
    assert result.approved is approved
    assert result.reason == ("user-confirmed" if approved else "user-denied")


def test_permission_gate_yolo_auto_and_high_risk_prompt(monkeypatch) -> None:
    automatic = check_permission("Run tests", RiskTier.CONFIRM, mode="yolo", interactive=True)
    assert automatic.approved is True
    assert automatic.reason == "yolo-auto"

    monkeypatch.setattr(permissions.Prompt, "ask", lambda *_args, **_kwargs: "n")
    denied = check_permission("Delete data", RiskTier.BLOCK, mode="yolo", interactive=True)
    assert denied.approved is False
    assert denied.reason == "yolo-prompt"

    noninteractive = check_permission(
        "Delete data", RiskTier.BLOCK, mode="yolo", interactive=False
    )
    assert noninteractive.approved is True
    assert noninteractive.reason == "yolo-auto"


def test_permission_gate_paranoid_auto_tier_uses_fallback() -> None:
    result = check_permission("Write file", RiskTier.AUTO, mode="paranoid", interactive=True)
    assert result.approved is True
    assert result.reason == "auto"
