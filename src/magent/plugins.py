"""Installable MagAgent extension packs."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import Any

from magent.config import CONFIG_DIR

PLUGIN_DIR = CONFIG_DIR / "plugins"
PLUGIN_STATE = CONFIG_DIR / "plugins.toml"


def list_plugins() -> dict[str, Any]:
    plugins = []
    state = _state()
    for path in sorted(PLUGIN_DIR.glob("*")) if PLUGIN_DIR.exists() else []:
        if path.is_dir():
            manifest = _manifest(path)
            plugins.append(
                {
                    "name": manifest.get("name", path.name),
                    "version": manifest.get("version", ""),
                    "enabled": bool(state.get(path.name, {}).get("enabled")),
                    "path": str(path),
                    "packs": _pack_paths(path),
                }
            )
    return {"ok": True, "plugins": plugins}


def install_plugin(source: str | Path, *, name: str = "", force: bool = False) -> dict[str, Any]:
    src = Path(source).expanduser().resolve()
    if not src.exists() or not src.is_dir():
        return {"ok": False, "error": f"Plugin source directory not found: {src}"}
    manifest = _manifest(src)
    plugin_name = name or manifest.get("name") or src.name
    target = PLUGIN_DIR / plugin_name
    if target.exists() and force:
        shutil.rmtree(target)
    if target.exists():
        return {"ok": False, "error": f"Plugin already installed: {plugin_name}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target)
    return {"ok": True, "plugin": plugin_name, "path": str(target), "packs": _pack_paths(target)}


def set_plugin_enabled(name: str, enabled: bool) -> dict[str, Any]:
    state = _state()
    state.setdefault(name, {})["enabled"] = enabled
    _write_state(state)
    return {"ok": True, "plugin": name, "enabled": enabled}


def enabled_plugin_paths() -> list[Path]:
    state = _state()
    return [
        PLUGIN_DIR / name
        for name, cfg in state.items()
        if cfg.get("enabled") and (PLUGIN_DIR / name).exists()
    ]


def _manifest(path: Path) -> dict[str, Any]:
    for name in ("magent-plugin.toml", "plugin.toml"):
        manifest = path / name
        if manifest.exists():
            try:
                with manifest.open("rb") as f:
                    data = tomllib.load(f)
                return data.get("plugin", data) if isinstance(data, dict) else {}
            except Exception:
                return {}
    return {}


def _pack_paths(path: Path) -> dict[str, str]:
    return {
        key: str(candidate)
        for key, candidate in {
            "skills": path / "skills",
            "recipes": path / "recipes",
            "agents": path / "agents",
            "tools": path / "tools",
            "mcp": path / "mcp.toml",
        }.items()
        if candidate.exists()
    }


def _state() -> dict[str, Any]:
    if not PLUGIN_STATE.exists():
        return {}
    try:
        with PLUGIN_STATE.open("rb") as f:
            data = tomllib.load(f)
        return data.get("plugins", data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(state: dict[str, Any]) -> None:
    import tomli_w

    PLUGIN_STATE.parent.mkdir(parents=True, exist_ok=True)
    with PLUGIN_STATE.open("wb") as f:
        tomli_w.dump({"plugins": state}, f)
