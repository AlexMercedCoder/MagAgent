"""Expanded local diagnostics for MagAgent projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magent.artifact_contracts import infer_expected_artifacts, verify_expected_artifacts
from magent.config_ux import provider_matrix
from magent.hooks import load_hooks
from magent.permission_ux import permission_status
from magent.plugins import list_plugins
from magent.workbench import project_diagnostics


def deep_diagnostics(
    username: str,
    config: Any,
    store: Any,
    *,
    project: str | Path = ".",
    prompt: str = "",
) -> dict[str, Any]:
    """Return a broad local diagnostics report for setup and active project work."""
    root = Path(project).resolve()
    base = project_diagnostics(root, store=store)
    mcp_servers = config.get("mcp", "servers", default={})
    hooks = load_hooks(root)
    plugins = list_plugins()
    permissions = permission_status(username)
    provider_rows = provider_matrix().get("providers", [])
    provider = next((item for item in provider_rows if item.get("id") == config.default_provider), {})
    artifact_paths = infer_expected_artifacts(prompt, cwd=root) if prompt else []
    artifact_audit = verify_expected_artifacts(artifact_paths)
    checks = [
        {"key": "project", "ok": all(item.get("ok", True) for item in base), "detail": base},
        {"key": "provider", "ok": bool(provider.get("ready")), "detail": provider},
        {
            "key": "mcp",
            "ok": isinstance(mcp_servers, dict),
            "detail": {"configured": sorted(mcp_servers) if isinstance(mcp_servers, dict) else []},
        },
        {"key": "hooks", "ok": True, "detail": hooks},
        {"key": "plugins", "ok": bool(plugins.get("ok", True)), "detail": plugins},
        {"key": "permissions", "ok": True, "detail": permissions},
    ]
    if prompt:
        checks.append({"key": "artifact_contract", "ok": artifact_audit["ok"], "detail": artifact_audit})
    return {
        "ok": all(item["ok"] for item in checks),
        "project": str(root),
        "checks": checks,
        "next": _next_actions(checks),
    }


def _next_actions(checks: list[dict[str, Any]]) -> list[str]:
    failed = {item["key"] for item in checks if not item.get("ok")}
    actions = []
    if "provider" in failed:
        actions.append("magent provider wizard")
    if "artifact_contract" in failed:
        actions.append("Retry with explicit filenames and inspect the artifact verification note.")
    return actions or ["No critical local diagnostics failed."]
