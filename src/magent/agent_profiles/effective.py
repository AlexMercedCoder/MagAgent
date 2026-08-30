"""Capability and policy narrowing for resolved OAP profiles."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from typing import Any

from magent.agent_profiles.models import Adjustment, EffectiveProfile, ResolvedProfile

_MODE_ORDER = {"paranoid": 0, "balanced": 1, "silent": 2, "yolo": 3}
_WRITEBACK_ORDER = {"off": 0, "propose": 1, "auto": 2}
_NETWORK_ORDER = {"none": 0, "read": 1, "full": 2}
_NETWORK_READ_TOOLS = {
    "web_search",
    "web_fetch",
    "deep_research",
    "browser_snapshot",
    "browser_screenshot",
    "webmcp_open",
    "webmcp_list_tools",
}
_NETWORK_TOOLS = _NETWORK_READ_TOOLS | {"http_request", "webmcp_call_tool"}
_TOOL_ALIASES = {
    "read": {"read_file", "read_file_range", "outline_file", "list_dir", "diff_files"},
    "write": {
        "write_file",
        "create_docx",
        "create_pptx",
        "create_svg",
        "create_diagram",
        "create_image",
        "generate_image",
    },
    "edit": {"edit_file"},
    "delete": {"delete_file"},
    "search": {"search_codebase"},
    "shell": {"run_shell", "run_python", "install_package", "git_op"},
    "web": {
        "web_search",
        "web_fetch",
        "deep_research",
        "http_request",
        "browser_snapshot",
        "browser_screenshot",
        "webmcp_open",
        "webmcp_list_tools",
        "webmcp_call_tool",
    },
}


def narrow_permission_mode(policy: str, requested: str) -> str:
    requested = {"deny": "paranoid", "ask": "balanced", "allow": "yolo"}.get(requested, requested)
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
        name
        for name in granted
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in expanded_patterns)
    }


def _documents(resolved: ResolvedProfile) -> tuple[dict[str, Any], ...]:
    return (*resolved.lineage, resolved.document)


def _references(value: Any) -> set[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    result = set()
    for item in value:
        name = item.get("name") if isinstance(item, dict) else item
        if str(name or "").strip():
            result.add(str(name).strip())
    return result


def _selection(
    documents: tuple[dict[str, Any], ...], section: str, key: str
) -> tuple[str, ...] | None:
    selected: set[str] | None = None
    for document in documents:
        container = document.get("spec", {}).get(section, {})
        if not isinstance(container, dict) or key not in container:
            continue
        requested = _references(container.get(key))
        selected = requested if selected is None else selected & requested
    return None if selected is None else tuple(sorted(selected))


def _subagent_policy(
    documents: tuple[dict[str, Any], ...], config: Any
) -> tuple[tuple[str, ...] | None, int, int, int]:
    selected: set[str] | None = None
    max_agents = int(getattr(config, "max_subagents", 3))
    max_parallel = int(getattr(config, "max_parallel_subagents", 2))
    max_depth = int(config.get("agent_profiles", "max_delegation_depth", default=3))
    for document in documents:
        runtime = document.get("spec", {}).get("runtime", {})
        if not isinstance(runtime, dict) or "subagents" not in runtime:
            continue
        raw = runtime.get("subagents")
        if isinstance(raw, dict):
            allowed = raw.get("allow", raw.get("profiles"))
            if allowed is not None:
                requested = _references(allowed)
                selected = requested if selected is None else selected & requested
            max_agents = min(max_agents, int(raw.get("max_subagents") or max_agents))
            max_parallel = min(max_parallel, int(raw.get("max_parallel") or max_parallel))
            max_depth = min(max_depth, int(raw.get("max_depth") or max_depth))
        else:
            requested = _references(raw)
            selected = requested if selected is None else selected & requested
    return (
        None if selected is None else tuple(sorted(selected)),
        max(0, max_agents),
        max(0, max_parallel),
        max(0, max_depth),
    )


def _mode_permissions(mode: str) -> tuple[bool, bool]:
    return mode in {"read", "read_write"}, mode in {"write", "read_write"}


def _memory_stores(
    documents: tuple[dict[str, Any], ...], config: Any
) -> tuple[tuple[str, str, str], ...]:
    configured_mode = str(getattr(config, "memory_mode", "read_write") or "read_write")
    stores: dict[tuple[str, str], tuple[bool, bool]] = {
        ("profile-state", "oap-state"): (True, True),
        ("user-graph", "maggraph"): _mode_permissions(configured_mode),
    }
    declared = False
    for document in documents:
        memory = document.get("spec", {}).get("memory", {})
        if not isinstance(memory, dict):
            continue
        if "mode" in memory:
            ceiling = _mode_permissions(str(memory.get("mode") or "off"))
            stores = {
                key: (access[0] and ceiling[0], access[1] and ceiling[1])
                for key, access in stores.items()
            }
        if "stores" not in memory:
            continue
        requested: dict[tuple[str, str], tuple[bool, bool]] = {}
        for item in memory.get("stores") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("kind") or "").strip()
            kind = str(item.get("kind") or "").strip()
            if not name or kind not in {"oap-state", "maggraph"}:
                continue
            requested[(name, kind)] = _mode_permissions(str(item.get("mode") or "read"))
        if not declared:
            stores = requested
            declared = True
        else:
            stores = {
                key: (stores[key][0] and requested[key][0], stores[key][1] and requested[key][1])
                for key in stores.keys() & requested.keys()
            }
    result = []
    for (name, kind), (read, write) in sorted(stores.items()):
        mode = "read_write" if read and write else "read" if read else "write" if write else "off"
        if mode != "off":
            result.append((name, kind, mode))
    return tuple(result)


def _intersect_optional(
    left: tuple[str, ...] | None, right: tuple[str, ...] | None
) -> tuple[str, ...] | None:
    if left is None:
        return right
    if right is None:
        return left
    return tuple(sorted(set(left) & set(right)))


def _intersect_stores(
    child: tuple[tuple[str, str, str], ...], parent: tuple[tuple[str, str, str], ...]
) -> tuple[tuple[str, str, str], ...]:
    parent_map = {(name, kind): _mode_permissions(mode) for name, kind, mode in parent}
    result = []
    for name, kind, mode in child:
        if (name, kind) not in parent_map:
            continue
        read, write = _mode_permissions(mode)
        parent_read, parent_write = parent_map[(name, kind)]
        read, write = read and parent_read, write and parent_write
        narrowed = (
            "read_write" if read and write else "read" if read else "write" if write else "off"
        )
        if narrowed != "off":
            result.append((name, kind, narrowed))
    return tuple(result)


def resolve_effective_profile(
    resolved: ResolvedProfile,
    config: Any,
    granted_tools: Iterable[str],
    *,
    parent: EffectiveProfile | None = None,
) -> EffectiveProfile:
    documents = _documents(resolved)
    adjustments: list[Adjustment] = []
    granted = set(granted_tools)
    effective_tools = set(granted)
    for document in documents:
        requested_spec = document.get("spec", {})
        tools = (
            requested_spec.get("tools", {}) if isinstance(requested_spec.get("tools"), dict) else {}
        )
        allow = [str(item) for item in tools.get("allow", ["*"])]
        deny = [str(item) for item in tools.get("deny", [])]
        before = set(effective_tools)
        effective_tools = _expanded(allow, effective_tools) - _expanded(deny, effective_tools)
        for name in sorted(before - effective_tools):
            adjustments.append(
                Adjustment("tools", name, None, "profile inheritance or policy denied the tool")
            )

    policy_mode = str(getattr(config, "permission_mode", "balanced"))
    mode = policy_mode
    network_access = "full"
    for document in documents:
        permissions = document.get("spec", {}).get("permissions", {})
        requested_mode = str(permissions.get("default") or mode)
        narrowed = narrow_permission_mode(mode, requested_mode)
        if narrowed != requested_mode:
            adjustments.append(
                Adjustment(
                    "permissions.default",
                    requested_mode,
                    narrowed,
                    "profile cannot widen inherited permissions",
                )
            )
        mode = narrowed
        requested_network = str(permissions.get("network") or network_access)
        requested_network = {"deny": "none", "ask": "read", "allow": "read"}.get(
            requested_network, requested_network
        )
        if requested_network not in _NETWORK_ORDER:
            requested_network = "none"
        network_access = min(
            (network_access, requested_network), key=lambda item: _NETWORK_ORDER[item]
        )

    provider = str(getattr(config, "default_provider", ""))
    model_id = str(getattr(config, "default_model", ""))
    for document in documents:
        requested_model = document.get("spec", {}).get("model", {})
        if isinstance(requested_model, dict):
            provider = str(requested_model.get("provider") or provider)
            model_id = str(requested_model.get("id") or model_id)
    config_turns = int(config.get("agent", "max_model_rounds_per_turn", default=16))
    max_turns = config_turns
    for document in documents:
        item_runtime = document.get("spec", {}).get("runtime", {})
        requested_turns = (
            int(item_runtime.get("max_turns") or max_turns)
            if isinstance(item_runtime, dict)
            else max_turns
        )
        if requested_turns > max_turns:
            adjustments.append(
                Adjustment(
                    "runtime.max_turns",
                    requested_turns,
                    max_turns,
                    "profile cannot raise the inherited turn limit",
                )
            )
        max_turns = min(max_turns, requested_turns)

    config_state = int(config.get("agent_profiles", "max_state_tokens", default=1200))
    max_state = min(config_state, int(getattr(config, "memory_budget_tokens", 4000)))
    for document in documents:
        context = document.get("spec", {}).get("context", {})
        budget = context.get("budget", {}) if isinstance(context, dict) else {}
        if isinstance(budget, dict) and budget.get("max_state_tokens") is not None:
            max_state = min(max_state, int(budget["max_state_tokens"]))

    ceiling = str(config.get("agent_profiles", "writeback", default="propose"))
    if ceiling not in _WRITEBACK_ORDER:
        ceiling = "propose"
    writeback = ceiling
    for document in documents:
        requested_writeback = str(document.get("lifecycle", {}).get("writeback") or writeback)
        if requested_writeback not in _WRITEBACK_ORDER:
            requested_writeback = "propose"
        writeback = min((requested_writeback, writeback), key=lambda item: _WRITEBACK_ORDER[item])
    configured_tool_budgets = config.get("tool_budgets", default={}) or {}
    narrowed_tool_budgets: dict[str, int] = {}
    for document in documents:
        item_runtime = document.get("spec", {}).get("runtime", {})
        requested_tool_budgets = (
            item_runtime.get("tool_budgets", {}) if isinstance(item_runtime, dict) else {}
        )
        if not isinstance(requested_tool_budgets, dict):
            continue
        for name, requested in requested_tool_budgets.items():
            budget_ceiling = narrowed_tool_budgets.get(
                str(name),
                int(
                    configured_tool_budgets.get(name, configured_tool_budgets.get("default", 8000))
                ),
            )
            narrowed_tool_budgets[str(name)] = min(int(requested), budget_ceiling)
    configured_spend = float(config.get("budgets", "session_usd", default=0.0) or 0.0)
    session_usd = configured_spend
    for document in documents:
        item_runtime = document.get("spec", {}).get("runtime", {})
        requested_spend = (
            float(item_runtime.get("session_usd") or session_usd)
            if isinstance(item_runtime, dict)
            else session_usd
        )
        session_usd = min(requested_spend, session_usd) if session_usd > 0 else requested_spend
    mcp_servers = _selection(documents, "tools", "mcp_servers")
    skills = _selection(documents, "tools", "skills")
    subagents, max_agents, max_parallel, max_depth = _subagent_policy(documents, config)
    stores = _memory_stores(documents, config)

    if parent is not None:
        before = set(effective_tools)
        effective_tools &= set(parent.tools)
        for name in sorted(before - effective_tools):
            adjustments.append(Adjustment("tools", name, None, "parent profile delegation ceiling"))
        mode = narrow_permission_mode(parent.permission_mode, mode)
        network_access = min(
            (network_access, getattr(parent, "network_access", "full")),
            key=lambda item: _NETWORK_ORDER[item],
        )
        writeback = min((writeback, parent.writeback), key=lambda item: _WRITEBACK_ORDER[item])
        max_turns = min(max_turns, parent.max_turns)
        max_state = min(max_state, parent.max_state_tokens)
        session_usd = (
            min(session_usd, parent.session_usd) if parent.session_usd > 0 else session_usd
        )
        mcp_servers = _intersect_optional(mcp_servers, parent.mcp_servers)
        skills = _intersect_optional(skills, parent.skills)
        max_agents = min(max_agents, parent.max_subagents)
        max_parallel = min(max_parallel, parent.max_parallel_subagents)
        max_depth = min(max_depth, max(0, parent.max_delegation_depth - 1))
        if parent.memory_stores is not None:
            stores = _intersect_stores(stores, parent.memory_stores)

    before_network = set(effective_tools)
    if network_access == "none":
        effective_tools -= _NETWORK_TOOLS
    elif network_access == "read":
        effective_tools -= _NETWORK_TOOLS - _NETWORK_READ_TOOLS
    for name in sorted(before_network - effective_tools):
        adjustments.append(
            Adjustment(
                "permissions.network",
                name,
                None,
                f"profile network access is {network_access}",
            )
        )

    return EffectiveProfile(
        resolved=resolved,
        tools=frozenset(effective_tools),
        permission_mode=mode,
        network_access=network_access,
        provider=provider,
        model=model_id,
        max_turns=max_turns,
        max_state_tokens=max_state,
        writeback=writeback,
        tool_budgets=tuple(sorted(narrowed_tool_budgets.items())),
        session_usd=session_usd,
        mcp_servers=mcp_servers,
        skills=skills,
        subagents=subagents,
        max_subagents=max_agents,
        max_parallel_subagents=max_parallel,
        max_delegation_depth=max_depth,
        memory_stores=stores,
        adjustments=tuple(adjustments),
    )
