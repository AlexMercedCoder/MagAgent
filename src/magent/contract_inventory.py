"""Canonical 1.0 release-candidate contract inventory."""

from __future__ import annotations

from typing import Any

from magent import __version__
from magent.config import DEFAULT_GLOBAL_CONFIG, DEFAULT_USER_PROFILE
from magent.desktop_api import platform_contracts

SCHEMA = "magent.contract-inventory.v1"

STABLE_PUBLIC_IMPORTS = (
    ("magent.agent", "AgentSession"),
    ("magent.tools", "ToolExecutor"),
    ("magent.workbench", "WorkbenchStore"),
    ("magent.workbench", "task_add"),
    ("magent.workbench_domains.plans", "save_plan"),
)

PERSISTENT_STATE_CONTRACTS = (
    {"name": "agent_profiles", "schema": "oap.v1", "status": "beta", "writes": "reviewed-state-only"},
)

STABLE_CLI_PREFIXES = {
    "ask",
    "chat",
    "configure",
    "doctor",
    "system contracts",
    "system compatibility",
    "system migrate",
    "system rollback",
    "execution list",
    "execution show",
    "execution events",
    "execution cancel",
    "memory search",
    "memory show",
    "plugin validate",
}


def contract_inventory(command_names: list[str] | None = None) -> dict[str, Any]:
    """Return every supported contract family with an explicit stability label."""
    platform = platform_contracts()
    commands = sorted(set(command_names or []))
    return {
        "ok": True,
        "schema": SCHEMA,
        "magent_version": __version__,
        "candidate": "1.0",
        "python_imports": [
            {"module": module, "symbol": symbol, "status": "stable"}
            for module, symbol in STABLE_PUBLIC_IMPORTS
        ],
        "cli": [
            {
                "command": command,
                "status": "stable" if command in STABLE_CLI_PREFIXES else "beta",
            }
            for command in commands
        ],
        "config": {
            "version": "1",
            "status": "stable",
            "global_keys": _config_keys(DEFAULT_GLOBAL_CONFIG),
            "user_keys": _config_keys(DEFAULT_USER_PROFILE),
            "unknown_keys": "preserved",
        },
        "machine": platform["contracts"],
        "persistent_state": list(PERSISTENT_STATE_CONTRACTS),
        "support": platform["support"],
        "rules": {
            "unknown_fields": "consumers must ignore unknown additive fields",
            "deprecation": "one prior minor release for stable removals",
            "downgrade": "newer persistent schemas are refused",
            "beta": "may change before 1.0 with migration notes",
            "experimental": "opt-in and outside the support promise",
        },
    }


def _config_keys(value: dict[str, Any], prefix: str = "") -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key, child in sorted(value.items()):
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            items.extend(_config_keys(child, path))
        else:
            items.append({"path": path, "type": type(child).__name__, "status": "stable"})
    return items
