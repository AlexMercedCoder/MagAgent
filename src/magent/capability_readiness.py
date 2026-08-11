"""Optional capability readiness without importing heavyweight integrations."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass


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
