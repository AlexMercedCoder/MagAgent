"""Tool backend metadata and gateway readiness helpers."""

from __future__ import annotations

from typing import Any


TOOL_BACKENDS: dict[str, dict[str, Any]] = {
    "local": {
        "label": "Local built-ins",
        "description": "Filesystem, shell, archives, SQLite, document, presentation, SVG, and diagram tools running locally.",
        "credential": "",
        "subscription": False,
    },
    "web": {
        "label": "Local web search/fetch",
        "description": "Built-in web_search, web_fetch, deep_research, and http_request tools.",
        "credential": "",
        "subscription": False,
    },
    "browser": {
        "label": "Local browser automation",
        "description": "Playwright-backed snapshots and screenshots when browser dependencies are installed.",
        "credential": "",
        "subscription": False,
    },
    "image": {
        "label": "Configured image model",
        "description": "AI image generation through the image_maker model role.",
        "credential": "provider credential for image_maker",
        "subscription": False,
    },
    "nous-portal": {
        "label": "Nous Portal tool gateway",
        "description": "Subscription-style backend for models and optional tool services when configured.",
        "credential": "NOUS_API_KEY or saved nous-portal credential",
        "subscription": True,
    },
    "opencode-go": {
        "label": "OpenCode Go subscription",
        "description": "Subscription-backed model access for coding workflows.",
        "credential": "OPENCODE_GO_KEY or saved opencode-go credential",
        "subscription": True,
    },
    "mcp": {
        "label": "MCP servers",
        "description": "Configured Model Context Protocol servers contributing external tools.",
        "credential": "server-specific",
        "subscription": False,
    },
}


def gateway_status(config: Any) -> dict[str, Any]:
    """Return tool backend readiness metadata."""
    providers = config.get("providers", default={}) or {}
    mcp_servers = config.get("mcp", "servers", default={}) or {}
    image_role = ""
    try:
        image_role = config.model_for_role("image_maker")
    except Exception:
        image_role = ""
    backends = []
    for key, item in TOOL_BACKENDS.items():
        enabled = key in {"local", "web"}
        if key == "browser":
            enabled = bool(config.get("tools", "browser_enabled", default=True))
        elif key == "image":
            enabled = bool(image_role)
        elif key in {"nous-portal", "opencode-go"}:
            enabled = key in providers
        elif key == "mcp":
            enabled = bool(mcp_servers)
        backends.append({"id": key, "enabled": enabled, **item})
    return {"ok": True, "backends": backends}


def explain_backend(name: str) -> dict[str, Any]:
    key = name.strip().lower()
    item = TOOL_BACKENDS.get(key)
    if not item:
        return {"ok": False, "error": f"Unknown tool backend: {name}", "known": sorted(TOOL_BACKENDS)}
    return {"ok": True, "id": key, **item}
