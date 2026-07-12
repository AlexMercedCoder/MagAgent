"""Installable MagAgent extension packs."""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

from magent.config import CONFIG_DIR

PLUGIN_DIR = CONFIG_DIR / "plugins"
PLUGIN_STATE = CONFIG_DIR / "plugins.toml"
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def _safe_plugin_name(value: str) -> dict[str, Any]:
    raw = str(value or "").strip()
    if "/" in raw or "\\" in raw:
        return {"ok": False, "error": f"Invalid plugin name: {value!r}. Path separators are not allowed."}
    name = raw
    if not name or name in {".", ".."} or not PLUGIN_NAME_RE.fullmatch(name):
        return {
            "ok": False,
            "error": f"Invalid plugin name: {value!r}. Use letters, numbers, dots, underscores, or dashes.",
        }
    return {"ok": True, "name": name}


def _plugin_target(name: str) -> dict[str, Any]:
    name_result = _safe_plugin_name(name)
    if not name_result["ok"]:
        return name_result
    root = PLUGIN_DIR.resolve(strict=False)
    target = (root / name_result["name"]).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError:
        return {"ok": False, "error": f"Plugin target escapes plugin directory: {name}"}
    return {"ok": True, "name": name_result["name"], "path": target}


def list_plugins() -> dict[str, Any]:
    plugins = []
    state = _state()
    for path in sorted(PLUGIN_DIR.glob("*")) if PLUGIN_DIR.exists() else []:
        if path.is_dir():
            manifest = normalize_plugin_metadata(path)
            plugins.append(
                {
                    "name": manifest.get("name", path.name),
                    "version": manifest.get("version", ""),
                    "enabled": bool(state.get(path.name, {}).get("enabled")),
                    "path": str(path),
                    "packs": _pack_paths(path),
                    "metadata": manifest,
                }
            )
    return {"ok": True, "plugins": plugins}


def install_plugin(source: str | Path, *, name: str = "", force: bool = False) -> dict[str, Any]:
    src = Path(source).expanduser().resolve()
    if not src.exists() or not src.is_dir():
        return {"ok": False, "error": f"Plugin source directory not found: {src}"}
    manifest = normalize_plugin_metadata(src)
    plugin_name_result = _safe_plugin_name(name or manifest.get("name") or src.name)
    if not plugin_name_result["ok"]:
        return plugin_name_result
    plugin_name = plugin_name_result["name"]
    target_result = _plugin_target(plugin_name)
    if not target_result["ok"]:
        return target_result
    target = target_result["path"]
    if target.exists() and force:
        shutil.rmtree(target)
    if target.exists():
        return {"ok": False, "error": f"Plugin already installed: {plugin_name}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target)
    _write_manifest(target, {**manifest, "name": plugin_name})
    return {
        "ok": True,
        "plugin": plugin_name,
        "name": plugin_name,
        "enabled": False,
        "path": str(target),
        "packs": _pack_paths(target),
        "metadata": normalize_plugin_metadata(target),
    }


def set_plugin_enabled(name: str, enabled: bool) -> dict[str, Any]:
    target_result = _plugin_target(name)
    if not target_result["ok"]:
        return {**target_result, "plugin": name, "name": name, "enabled": enabled}
    exists = target_result["path"].exists()
    if not exists:
        return {"ok": False, "plugin": name, "name": name, "enabled": enabled, "error": f"Plugin not installed: {name}"}
    state = _state()
    state.setdefault(name, {})["enabled"] = enabled
    _write_state(state)
    return {"ok": True, "plugin": name, "name": name, "enabled": enabled}


def enabled_plugin_paths() -> list[Path]:
    state = _state()
    return [
        PLUGIN_DIR / name
        for name, cfg in state.items()
        if cfg.get("enabled") and (PLUGIN_DIR / name).exists()
    ]


def enabled_plugin_mcp_servers() -> dict[str, Any]:
    servers: dict[str, Any] = {}
    for plugin_path in enabled_plugin_paths():
        plugin_name = plugin_path.name
        for server_name, cfg in _mcp_servers_from_path(plugin_path).items():
            key = server_name if server_name not in servers else f"{plugin_name}__{server_name}"
            servers[key] = {**cfg, "source_plugin": plugin_name}
    return servers


def import_mcp_plugin(
    source: str | Path,
    *,
    name: str = "",
    force: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    src = Path(source).expanduser().resolve()
    servers = _mcp_servers_from_source(src)
    if not servers:
        return {"ok": False, "error": f"No MCP servers found in {src}"}
    plugin_name_result = _safe_plugin_name(name or f"{src.stem}-mcp")
    if not plugin_name_result["ok"]:
        return plugin_name_result
    plugin_name = plugin_name_result["name"]
    target_result = _plugin_target(plugin_name)
    if not target_result["ok"]:
        return target_result
    target = target_result["path"]
    if target.exists() and force:
        shutil.rmtree(target)
    if target.exists():
        return {"ok": False, "error": f"Plugin already installed: {plugin_name}"}
    target.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        target,
        {
            "name": plugin_name,
            "description": "Imported MCP server pack",
            "compatibility": ["mcp"],
            "capabilities": ["mcp"],
            "permissions": ["external_process"],
            "trust": "local",
            "source_url": str(src),
        },
    )
    _write_mcp_servers(target / "mcp.toml", servers)
    result: dict[str, Any] = {
        "ok": True,
        "plugin": plugin_name,
        "name": plugin_name,
        "enabled": False,
        "path": str(target),
        "servers": sorted(servers),
        "packs": _pack_paths(target),
    }
    if apply:
        result["apply"] = apply_plugin_mcp(plugin_name)
    return result


def apply_plugin_mcp(name: str, *, force: bool = False) -> dict[str, Any]:
    target_result = _plugin_target(name)
    if not target_result["ok"]:
        return target_result
    plugin_path = target_result["path"]
    if not plugin_path.exists():
        return {"ok": False, "error": f"Plugin not installed: {name}"}
    servers = _mcp_servers_from_path(plugin_path)
    if not servers:
        return {"ok": False, "error": f"Plugin has no MCP servers: {name}"}

    import tomli_w

    from magent.config import GLOBAL_CONFIG, load_global_config

    cfg = load_global_config()
    cfg.setdefault("mcp", {}).setdefault("servers", {})
    added: list[str] = []
    skipped: list[str] = []
    for server_name, server_cfg in servers.items():
        target_name = server_name
        if target_name in cfg["mcp"]["servers"] and not force:
            skipped.append(target_name)
            continue
        cfg["mcp"]["servers"][target_name] = server_cfg
        added.append(target_name)
    GLOBAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with GLOBAL_CONFIG.open("wb") as f:
        tomli_w.dump(cfg, f)
    return {"ok": True, "plugin": name, "added": added, "skipped": skipped, "config": str(GLOBAL_CONFIG)}


def import_compat_plugin(
    ecosystem: str,
    source: str | Path,
    *,
    name: str = "",
    force: bool = False,
) -> dict[str, Any]:
    src = Path(source).expanduser().resolve()
    if not src.exists():
        return {"ok": False, "error": f"Import source not found: {src}"}
    ecosystem = ecosystem.replace("_", "-").lower()
    if ecosystem not in {"opencode", "claude", "codex-skill", "gemini"}:
        return {"ok": False, "error": f"Unsupported importer: {ecosystem}"}
    plugin_name_result = _safe_plugin_name(name or f"{src.stem}-{ecosystem}")
    if not plugin_name_result["ok"]:
        return plugin_name_result
    plugin_name = plugin_name_result["name"]
    target_result = _plugin_target(plugin_name)
    if not target_result["ok"]:
        return target_result
    target = target_result["path"]
    if target.exists() and force:
        shutil.rmtree(target)
    if target.exists():
        return {"ok": False, "error": f"Plugin already installed: {plugin_name}"}
    target.mkdir(parents=True, exist_ok=True)
    converted: dict[str, list[str]] = {"agents": [], "skills": [], "recipes": [], "hooks": []}
    if ecosystem == "opencode":
        _import_opencode(src, target, converted)
    elif ecosystem == "claude":
        _import_claude(src, target, converted)
    elif ecosystem == "gemini":
        _import_gemini(src, target, converted)
    else:
        _import_codex_skill(src, target, converted)
    _copy_mcp_if_present(src, target, converted)
    _write_manifest(
        target,
        {
            "name": plugin_name,
            "description": f"Imported {ecosystem} compatibility pack",
            "compatibility": [ecosystem],
            "capabilities": sorted(key for key, values in converted.items() if values),
            "permissions": _infer_permissions(target),
            "trust": "local",
            "source_url": str(src),
        },
    )
    return {
        "ok": True,
        "plugin": plugin_name,
        "name": plugin_name,
        "enabled": False,
        "path": str(target),
        "ecosystem": ecosystem,
        "converted": converted,
        "packs": _pack_paths(target),
        "metadata": normalize_plugin_metadata(target),
    }


def normalize_plugin_metadata(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    native = _native_manifest(root)
    foreign = _foreign_manifest(root)
    inferred = _inferred_metadata(root)
    metadata = {
        "name": root.name,
        "version": "",
        "description": "",
        "source_url": "",
        "compatibility": [],
        "capabilities": [],
        "permissions": [],
        "trust": "local",
    }
    compatibility: list[str] = []
    capabilities: list[str] = []
    permissions: list[str] = []
    for source in (inferred, foreign, native):
        compatibility.extend(_as_list(source.get("compatibility")))
        capabilities.extend(_as_list(source.get("capabilities")))
        permissions.extend(_as_list(source.get("permissions")))
        metadata.update(
            {
                k: v
                for k, v in source.items()
                if k not in {"compatibility", "capabilities", "permissions"} and v not in ("", [], None)
            }
        )
    metadata["compatibility"] = sorted(set(compatibility))
    metadata["capabilities"] = sorted(set(capabilities))
    metadata["permissions"] = sorted(set(permissions))
    return metadata


def _native_manifest(path: Path) -> dict[str, Any]:
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


def _foreign_manifest(path: Path) -> dict[str, Any]:
    plugin_json = path / "plugin.json"
    if plugin_json.exists():
        try:
            data = json.loads(plugin_json.read_text(encoding="utf-8"))
            return {
                "name": data.get("name") or data.get("id") or path.name,
                "version": data.get("version", ""),
                "description": data.get("description", ""),
                "source_url": data.get("repository") or data.get("homepage") or "",
                "compatibility": ["plugin-json"],
                "capabilities": _as_list(data.get("capabilities")),
                "permissions": _as_list(data.get("permissions")),
            }
        except Exception:
            return {"compatibility": ["plugin-json"]}
    package_json = path / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            repo = data.get("repository", "")
            if isinstance(repo, dict):
                repo = repo.get("url", "")
            return {
                "name": str(data.get("name") or path.name).split("/")[-1],
                "version": data.get("version", ""),
                "description": data.get("description", ""),
                "source_url": repo or data.get("homepage") or "",
                "compatibility": ["node-package"],
                "capabilities": ["mcp"] if "mcp" in json.dumps(data).lower() else [],
            }
        except Exception:
            return {"compatibility": ["node-package"]}
    return {}


def _inferred_metadata(path: Path) -> dict[str, Any]:
    compatibility = []
    capabilities = []
    if (path / "AGENTS.md").exists():
        compatibility.append("agents-md")
        capabilities.append("agents")
    if (path / "CLAUDE.md").exists() or (path / ".claude").exists():
        compatibility.append("claude")
        capabilities.extend(["agents", "recipes"])
    if (path / "GEMINI.md").exists() or (path / ".gemini").exists():
        compatibility.append("gemini")
        capabilities.extend(["agents", "recipes", "skills"])
    if (path / "SKILL.md").exists():
        compatibility.append("codex-skill")
        capabilities.append("skills")
    for key in _pack_paths(path):
        capabilities.append(key)
        if key == "mcp":
            compatibility.append("mcp")
    return {
        "compatibility": sorted(set(compatibility)),
        "capabilities": sorted(set(capabilities)),
        "permissions": _infer_permissions(path),
    }


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


def _import_opencode(src: Path, target: Path, converted: dict[str, list[str]]) -> None:
    _copy_markdown_dir(src / "agents", target / "agents", converted["agents"])
    _copy_markdown_dir(src / ".opencode" / "agents", target / "agents", converted["agents"])
    _copy_markdown_dir(src / "commands", target / "recipes", converted["recipes"])
    if (src / "AGENTS.md").exists():
        _write_agent_from_markdown(src / "AGENTS.md", target / "agents" / "opencode.md", converted["agents"])


def _import_claude(src: Path, target: Path, converted: dict[str, list[str]]) -> None:
    _copy_markdown_dir(src / ".claude" / "agents", target / "agents", converted["agents"])
    _copy_markdown_dir(src / ".claude" / "commands", target / "recipes", converted["recipes"])
    if (src / "CLAUDE.md").exists():
        _write_agent_from_markdown(src / "CLAUDE.md", target / "agents" / "claude.md", converted["agents"])


def _import_codex_skill(src: Path, target: Path, converted: dict[str, list[str]]) -> None:
    skill_file = src if src.is_file() and src.name == "SKILL.md" else src / "SKILL.md"
    if skill_file.exists():
        skill_name = skill_file.parent.name if skill_file.parent != src.parent else src.stem
        dest_dir = target / "skills" / _safe_name(skill_name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_file, dest_dir / "SKILL.md")
        converted["skills"].append(str((dest_dir / "SKILL.md").relative_to(target)))
    elif src.is_dir():
        _copy_markdown_dir(src, target / "skills" / _safe_name(src.name), converted["skills"])


def _import_gemini(src: Path, target: Path, converted: dict[str, list[str]]) -> None:
    _copy_markdown_dir(src / "agents", target / "agents", converted["agents"])
    _copy_markdown_dir(src / ".gemini" / "agents", target / "agents", converted["agents"])
    _copy_markdown_dir(src / "commands", target / "recipes", converted["recipes"])
    _copy_markdown_dir(src / ".gemini" / "commands", target / "recipes", converted["recipes"])
    _copy_markdown_dir(src / "skills", target / "skills" / _safe_name(src.name), converted["skills"])
    _copy_markdown_dir(src / ".gemini" / "skills", target / "skills" / _safe_name(src.name), converted["skills"])
    if (src / "GEMINI.md").exists():
        _write_agent_from_markdown(src / "GEMINI.md", target / "agents" / "gemini.md", converted["agents"])


def _copy_markdown_dir(src: Path, dest: Path, converted: list[str]) -> None:
    if not src.exists() or not src.is_dir():
        return
    for path in sorted(src.glob("*.md")):
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / path.name
        shutil.copy2(path, target)
        converted.append(str(target.relative_to(dest.parent.parent if len(dest.parts) > 1 else dest)))


def _write_agent_from_markdown(src: Path, dest: Path, converted: list[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = src.read_text(encoding="utf-8", errors="replace")
    dest.write_text(
        f"---\ndescription: Imported from {src.name}\nmode: subagent\n---\n\n{body}",
        encoding="utf-8",
    )
    converted.append(str(dest.relative_to(dest.parent.parent)))


def _copy_mcp_if_present(src: Path, target: Path, converted: dict[str, list[str]]) -> None:
    servers = _mcp_servers_from_source(src)
    if servers:
        _write_mcp_servers(target / "mcp.toml", servers)
        converted.setdefault("mcp", []).extend(sorted(servers))


def _mcp_servers_from_path(path: Path) -> dict[str, Any]:
    return _mcp_servers_from_source(path / "mcp.toml")


def _mcp_servers_from_source(source: Path) -> dict[str, Any]:
    candidates = [source]
    if source.is_dir():
        candidates = [
            source / "mcp.toml",
            source / ".mcp.toml",
            source / "config.toml",
            source / "mcp.json",
            source / "plugin.json",
            source / "package.json",
        ]
    for candidate in candidates:
        if not candidate.exists() or candidate.is_dir():
            continue
        try:
            if candidate.suffix == ".json":
                data = json.loads(candidate.read_text(encoding="utf-8"))
            else:
                with candidate.open("rb") as f:
                    data = tomllib.load(f)
        except Exception:
            continue
        servers = _extract_mcp_servers(data)
        if servers:
            return servers
    return {}


def _extract_mcp_servers(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("mcp"), dict) and isinstance(data["mcp"].get("servers"), dict):
        return data["mcp"]["servers"]
    if isinstance(data.get("servers"), dict):
        return data["servers"]
    if isinstance(data.get("mcpServers"), dict):
        return data["mcpServers"]
    if {"command", "args"} <= set(data):
        return {"default": data}
    return {}


def _write_manifest(path: Path, metadata: dict[str, Any]) -> None:
    import tomli_w

    path.mkdir(parents=True, exist_ok=True)
    with (path / "magent-plugin.toml").open("wb") as f:
        tomli_w.dump({"plugin": metadata}, f)


def _write_mcp_servers(path: Path, servers: dict[str, Any]) -> None:
    import tomli_w

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump({"mcp": {"servers": servers}}, f)


def _infer_permissions(path: Path) -> list[str]:
    permissions = []
    if (path / "mcp.toml").exists() or _mcp_servers_from_source(path):
        permissions.append("external_process")
    if (path / "tools").exists():
        permissions.append("tools")
    return sorted(set(permissions))


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple | set):
        return [str(item) for item in value]
    return [str(value)]


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-") or "imported"


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
