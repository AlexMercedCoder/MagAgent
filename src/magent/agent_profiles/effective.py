"""Capability and policy narrowing for resolved OAP profiles."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from typing import Any

from magent.agent_profiles.models import Adjustment, EffectiveProfile, ResolvedProfile

_MODE_ORDER = {"paranoid": 0, "balanced": 1, "silent": 2, "yolo": 3}
_WRITEBACK_ORDER = {"off": 0, "propose": 1, "auto": 2}
_TOOL_ALIASES = {
    "read": {"read_file", "read_file_range", "outline_file", "list_dir", "diff_files"},
    "write": {"write_file", "create_docx", "create_pptx", "create_svg", "create_diagram", "create_image", "generate_image"},
    "edit": {"edit_file"},
    "delete": {"delete_file"},
    "search": {"search_codebase"},
    "shell": {"run_shell", "run_python", "install_package", "git_op"},
    "web": {"web_search", "web_fetch", "deep_research", "http_request", "browser_snapshot", "browser_screenshot"},
}


def narrow_permission_mode(policy: str, requested: str) -> str:
    policy = policy if policy in _MODE_ORDER else "balanced"
    requested = requested if requested in _MODE_ORDER else policy
    return min((policy, requested), key=lambda item: _MODE_ORDER[item])


def _expanded(patterns: Iterable[str], granted: set[str]) -> set[str]:
    expanded_patterns: list[str] = []
    explicit: set[str] = set()
    for pattern in patterns:
        if pattern in _TOOL_ALIASES:
            explicit.update(_TOOL_ALIASES[pattern])
        else:
            expanded_patterns.append(pattern)
    return (explicit & granted) | {
        name for name in granted if any(fnmatch.fnmatchcase(name, pattern) for pattern in expanded_patterns)
    }


def resolve_effective_profile(
    resolved: ResolvedProfile,
    config: Any,
    granted_tools: Iterable[str],
) -> EffectiveProfile:
    spec = resolved.document.get("spec", {})
    adjustments: list[Adjustment] = []
    granted = set(granted_tools)
    tools = spec.get("tools", {}) if isinstance(spec.get("tools"), dict) else {}
    allow = [str(item) for item in tools.get("allow", ["*"])]
    deny = [str(item) for item in tools.get("deny", [])]
    effective_tools = _expanded(allow, granted) - _expanded(deny, granted)
    requested_names = _expanded(allow, granted | set(allow))
    for name in sorted(requested_names - effective_tools):
        adjustments.append(Adjustment("tools", name, None, "tool is denied or unavailable in harness policy"))

    policy_mode = str(getattr(config, "permission_mode", "balanced"))
    requested_mode = str(spec.get("permissions", {}).get("default") or policy_mode)
    mode = narrow_permission_mode(policy_mode, requested_mode)
    if mode != requested_mode:
        adjustments.append(Adjustment("permissions.default", requested_mode, mode, "profile cannot widen harness permissions"))

    model = spec.get("model", {}) if isinstance(spec.get("model"), dict) else {}
    provider = str(model.get("provider") or getattr(config, "default_provider", ""))
    model_id = str(model.get("id") or getattr(config, "default_model", ""))
    runtime = spec.get("runtime", {}) if isinstance(spec.get("runtime"), dict) else {}
    config_turns = int(config.get("agent", "max_model_rounds_per_turn", default=16))
    requested_turns = int(runtime.get("max_turns") or config_turns)
    max_turns = min(requested_turns, config_turns)
    if max_turns != requested_turns:
        adjustments.append(Adjustment("runtime.max_turns", requested_turns, max_turns, "profile cannot raise the harness turn limit"))

    context = spec.get("context", {}) if isinstance(spec.get("context"), dict) else {}
    budget = context.get("budget", {}) if isinstance(context.get("budget"), dict) else {}
    config_state = int(config.get("agent_profiles", "max_state_tokens", default=1200))
    requested_state = int(budget.get("max_state_tokens") or config_state)
    max_state = min(requested_state, config_state, int(getattr(config, "memory_budget_tokens", 4000)))
    if max_state != requested_state:
        adjustments.append(Adjustment("context.budget.max_state_tokens", requested_state, max_state, "profile state is bounded by context policy"))

    lifecycle = resolved.document.get("lifecycle", {})
    requested_writeback = str(lifecycle.get("writeback") or "propose")
    ceiling = str(config.get("agent_profiles", "writeback", default="propose"))
    if requested_writeback not in _WRITEBACK_ORDER:
        requested_writeback = "propose"
    if ceiling not in _WRITEBACK_ORDER:
        ceiling = "propose"
    writeback = min((requested_writeback, ceiling), key=lambda item: _WRITEBACK_ORDER[item])
    if writeback != requested_writeback:
        adjustments.append(Adjustment("lifecycle.writeback", requested_writeback, writeback, "configured writeback ceiling"))
    configured_tool_budgets = config.get("tool_budgets", default={}) or {}
    requested_tool_budgets = runtime.get("tool_budgets", {}) if isinstance(runtime.get("tool_budgets"), dict) else {}
    narrowed_tool_budgets: dict[str, int] = {}
    for name, requested in requested_tool_budgets.items():
        budget_ceiling = int(
            configured_tool_budgets.get(name, configured_tool_budgets.get("default", 8000))
        )
        narrowed_tool_budgets[str(name)] = min(int(requested), budget_ceiling)
        if narrowed_tool_budgets[str(name)] != int(requested):
            adjustments.append(Adjustment(f"runtime.tool_budgets.{name}", requested, narrowed_tool_budgets[str(name)], "profile cannot raise tool output budget"))
    configured_spend = float(config.get("budgets", "session_usd", default=0.0) or 0.0)
    requested_spend = float(runtime.get("session_usd") or configured_spend)
    session_usd = min(requested_spend, configured_spend) if configured_spend > 0 else requested_spend
    if configured_spend > 0 and session_usd != requested_spend:
        adjustments.append(Adjustment("runtime.session_usd", requested_spend, session_usd, "profile cannot raise session spend budget"))
    return EffectiveProfile(
        resolved, frozenset(effective_tools), mode, provider, model_id, max_turns,
        max_state, writeback, tuple(sorted(narrowed_tool_budgets.items())), session_usd,
        tuple(adjustments),
    )
