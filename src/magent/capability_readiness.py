"""Optional capability readiness without importing heavyweight integrations."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from magent import __version__


@dataclass(frozen=True)
class CapabilityReadiness:
    capability: str
    available: bool
    missing_modules: tuple[str, ...]
    install: str


CAPABILITY_MODULES: dict[str, tuple[str, ...]] = {
    "browser": ("playwright", "trafilatura", "bs4", "lxml"),
    "desktop": ("pyperclip", "psutil", "plyer"),
    "docs": ("docx", "pptx", "openpyxl", "fpdf"),
    "gateway": ("slack_bolt", "discord", "telegram"),
    "lsp": ("pylsp",),
    "mcp": ("mcp", "httpx2"),
    "media": ("PIL",),
}


def capability_readiness(capability: str) -> CapabilityReadiness:
    normalized = capability.strip().lower()
    if normalized not in CAPABILITY_MODULES:
        raise ValueError(f"Unknown optional capability: {capability}")
    missing = tuple(
        module
        for module in CAPABILITY_MODULES[normalized]
        if importlib.util.find_spec(module) is None
    )
    return CapabilityReadiness(
        capability=normalized,
        available=not missing,
        missing_modules=missing,
        install=f'python -m pip install "mag-agent[{normalized}]"',
    )


def readiness_report() -> dict[str, object]:
    capabilities = [asdict(capability_readiness(name)) for name in sorted(CAPABILITY_MODULES)]
    return {
        "ok": all(item["available"] for item in capabilities),
        "core_ready": True,
        "capabilities": capabilities,
        "full_install": 'python -m pip install "mag-agent[full]"',
    }


def capability_report() -> dict[str, Any]:
    reasons: list[str] = []
    package = importlib.util.find_spec("playwright") is not None
    browser = False
    if package:
        try:
            from playwright._impl._driver import compute_driver_executable

            node, cli = compute_driver_executable()
            script = (
                "process.stdout.write(require("
                + json.dumps(str(Path(cli).parent))
                + ").chromium.executablePath())"
            )
            result = subprocess.run(
                [node, "-e", script], capture_output=True, text=True, timeout=3, check=True
            )
            browser = Path(result.stdout).is_file()
        except Exception:
            reasons.append("Browser driver could not be inspected.")
    if not package:
        reasons.append("Install the webmcp optional dependency pack.")
    if not browser:
        reasons.append("Install the Playwright Chromium browser.")
    try:
        from magent.browser import normalize_webmcp_origins
        from magent.config import load_config

        origins = normalize_webmcp_origins(load_config().get("webmcp", "origins", default=None))
    except (ValueError, RuntimeError):
        origins = ()
        reasons.append("Configure at least one valid exact HTTPS origin.")
    return {
        "schema": "agent-runtime.capabilities.v1",
        "harness": "magagent",
        "version": __version__,
        "supported": {"aais": True, "webmcp": True, "oap": "1.0", "ags": "1.0"},
        "ready": {"webmcp": bool(package and browser and origins)},
        "webmcp": {
            "package_installed": package,
            "browser_installed": browser,
            "origins": list(origins),
            "registry_status": "not_checked",
            "reasons": reasons,
        },
        "limits": [
            "Live registry, credentials and profile policy are checked by the harness at execution."
        ],
    }
