"""Friendly permission profile helpers."""

from __future__ import annotations

from typing import Any

from magent.config import load_user_profile, save_user_profile

PERMISSION_MODES: dict[str, str] = {
    "silent": "Auto-run most low and medium risk actions; tier-3 actions still require typed confirmation.",
    "balanced": "Default. Auto-run low-risk actions, confirm medium/high risk actions.",
    "paranoid": "Only silent reads run automatically; almost every action asks first.",
    "yolo": "Auto-run almost everything. Useful only in externally sandboxed environments.",
}


def permission_status(username: str) -> dict[str, Any]:
    profile = load_user_profile(username)
    mode = profile.get("permissions", {}).get("mode", "balanced")
    return {
        "ok": True,
        "mode": mode,
        "description": PERMISSION_MODES.get(mode, ""),
        "allowed_shell_patterns": profile.get("permissions", {}).get("allowed_shell_patterns", []),
    }


def permission_explain(mode: str) -> dict[str, Any]:
    mode = mode.strip().lower()
    if mode not in PERMISSION_MODES:
        return {"ok": False, "error": f"Unknown permission mode: {mode}", "known": sorted(PERMISSION_MODES)}
    return {"ok": True, "mode": mode, "description": PERMISSION_MODES[mode]}


def permission_set(username: str, mode: str) -> dict[str, Any]:
    mode = mode.strip().lower()
    if mode not in PERMISSION_MODES:
        return {"ok": False, "error": f"Unknown permission mode: {mode}", "known": sorted(PERMISSION_MODES)}
    profile = load_user_profile(username)
    profile.setdefault("permissions", {})["mode"] = mode
    save_user_profile(username, profile)
    return {"ok": True, "mode": mode, "description": PERMISSION_MODES[mode]}


def permission_propose(text: str) -> dict[str, Any]:
    """Parse a limited natural-language permission request into a suggested command."""
    normalized = text.lower()
    for mode in PERMISSION_MODES:
        if mode in normalized:
            return {
                "ok": True,
                "mode": mode,
                "risk": "high" if mode == "yolo" else "normal",
                "command": f"magent permission set {mode}",
                "description": PERMISSION_MODES[mode],
            }
    patterns = []
    for word, command in (("pytest", "pytest *"), ("ruff", "ruff *"), ("git", "git *"), ("uv", "uv *")):
        if word in normalized:
            patterns.append(command)
    return {
        "ok": True,
        "mode": "",
        "allowed_shell_patterns": sorted(set(patterns)),
        "risk": "normal" if patterns else "unknown",
        "command": "magent config propose \"allow selected shell commands\"",
        "description": "Use config proposals to review shell allowlist changes before applying them.",
    }
