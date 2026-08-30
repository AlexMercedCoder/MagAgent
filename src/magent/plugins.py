"""Installable MagAgent extension packs."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from magent.config import CONFIG_DIR

PLUGIN_DIR = CONFIG_DIR / "plugins"
_SAFE_MCP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
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


def _contained_paths(root: Path, entries: Any, label: str) -> list[Path]:
    """Resolve plugin-supplied relative paths, refusing anything outside `root`.

    These entries come from inside the plugin's own report.json and became
    `--extension` arguments to a subprocess, so `../../..` in one of them meant
    an arbitrary file was loaded as an extension.
    """
    resolved_root = root.resolve(strict=False)
    paths: list[Path] = []
    for item in entries or []:
        if not isinstance(item, str) or not item.strip():
            continue
        candidate = (resolved_root / item).resolve(strict=False)
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            raise ValueError(f"{label} entry escapes the plugin package: {item!r}") from None
        paths.append(candidate)
    return paths


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
            from magent.plugin_sdk import verify_plugin

            manifest = normalize_plugin_metadata(path)
            verification = verify_plugin(path)
            plugins.append(
                {
                    "name": manifest.get("name", path.name),
                    "version": manifest.get("version", ""),
                    "enabled": bool(state.get(path.name, {}).get("enabled")),
                    "path": str(path),
                    "packs": _pack_paths(path),
                    "metadata": manifest,
                    "integrity": verification.get("integrity", "unrecorded"),
                    "valid": verification.get("ok", False),
                    "digest": verification.get("digest", ""),
                    "grants": state.get(path.name, {}).get("grants", {}),
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
    from magent.plugin_sdk import validate_plugin

    validation = validate_plugin(target, strict=True)
    if not validation["ok"]:
        shutil.rmtree(target)
        return {"ok": False, "error": "Plugin conformance failed", "validation": validation}
    return {
        "ok": True,
        "plugin": plugin_name,
        "name": plugin_name,
        "enabled": False,
        "path": str(target),
        "packs": _pack_paths(target),
        "metadata": normalize_plugin_metadata(target),
        "validation": validation,
    }


def set_plugin_enabled(name: str, enabled: bool) -> dict[str, Any]:
    target_result = _plugin_target(name)
    if not target_result["ok"]:
        return {**target_result, "plugin": name, "name": name, "enabled": enabled}
    exists = target_result["path"].exists()
    if not exists:
        return {"ok": False, "plugin": name, "name": name, "enabled": enabled, "error": f"Plugin not installed: {name}"}
    if enabled:
        from magent.plugin_sdk import verify_plugin

        verification = verify_plugin(target_result["path"])
        if not verification["ok"]:
            return {
                "ok": False,
                "plugin": name,
                "name": name,
                "enabled": False,
                "error": "Plugin integrity or conformance check failed",
                "verification": verification,
            }
    state = _state()
    state.setdefault(name, {})["enabled"] = enabled
    _write_state(state)
    return {"ok": True, "plugin": name, "name": name, "enabled": enabled}


def uninstall_plugin(name: str) -> dict[str, Any]:
    """Remove one installed plugin after the caller has confirmed deletion."""
    target_result = _plugin_target(name)
    if not target_result.get("ok"):
        return target_result
    target = target_result["path"]
    if not target.is_dir():
        return {"ok": False, "error": f"Plugin not installed: {name}"}
    state = _state()
    state.pop(target_result["name"], None)
    _write_state(state)
    shutil.rmtree(target)
    return {"ok": True, "plugin": target_result["name"], "removed": True}


def set_plugin_grant(
    name: str,
    *,
    scope: str,
    permissions: list[str],
    project: str = "",
) -> dict[str, Any]:
    """Record reviewed capability grants without treating instructions as authority."""
    from magent.plugin_sdk import KNOWN_PERMISSIONS

    target_result = _plugin_target(name)
    if not target_result["ok"] or not target_result["path"].exists():
        return {"ok": False, "error": f"Plugin not installed: {name}"}
    if scope not in {"user", "project"}:
        return {"ok": False, "error": "scope must be user or project"}
    requested = sorted(set(str(item) for item in permissions))
    unknown = sorted(set(requested) - KNOWN_PERMISSIONS)
    if unknown:
        return {"ok": False, "error": f"Unknown permissions: {', '.join(unknown)}"}
    scope_key = "user" if scope == "user" else str(Path(project).expanduser().resolve())
    if scope == "project" and not project:
        return {"ok": False, "error": "project scope requires --project"}
    state = _state()
    plugin_state = state.setdefault(name, {})
    plugin_state.setdefault("grants", {})[scope_key] = requested
    _write_state(state)
    return {"ok": True, "plugin": name, "scope": scope, "scope_key": scope_key, "permissions": requested}


def enabled_plugin_paths() -> list[Path]:
    """Directories of enabled plugins.

    Keys come from plugins.toml verbatim and feed load_external_graph_checkers,
    which *execs Python*, so each one goes through the same containment check
    as any other plugin name.
    """
    paths: list[Path] = []
    for name, cfg in _state().items():
        if not cfg.get("enabled"):
            continue
        target = _plugin_target(str(name))
        if not target.get("ok"):
            continue
        if target["path"].exists():
            paths.append(target["path"])
    return paths


def load_external_graph_checkers() -> list[str]:
    """Load AGS criterion checkers from explicitly enabled plugin packs."""
    loaded = []
    for root in enabled_plugin_paths():
        module_path = root / "agraph_checkers.py"
        if not module_path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(f"magent_plugin_{root.name}_agraph", module_path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if callable(register):
            from magent.agraph.criteria import register_external_checker

            register(register_external_checker)
            loaded.append(root.name)
    return loaded


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
    _write_manifest(target, normalize_plugin_metadata(target))
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


def _mcp_server_problem(server_name: str, server_cfg: Any) -> str:
    """Describe why a plugin-supplied MCP server entry is unusable, or "".

    Entries were written into the global config with no shape validation at
    all, and MCP servers are launched as subprocesses.
    """
    if not _SAFE_MCP_NAME.fullmatch(server_name):
        return f"invalid server name {server_name!r}"
    if not isinstance(server_cfg, dict):
        return "server entry must be a table"

    command = server_cfg.get("command")
    url = server_cfg.get("url")
    if command is None and url is None:
        return "server entry needs a 'command' or a 'url'"
    if command is not None and not isinstance(command, str):
        return "'command' must be a string"
    if command is not None and not command.strip():
        return "'command' must not be empty"

    args = server_cfg.get("args", [])
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        return "'args' must be a list of strings"

    env = server_cfg.get("env", {})
    if not isinstance(env, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()
    ):
        return "'env' must be a table of strings"

    if url is not None and not isinstance(url, str):
        return "'url' must be a string"
    return ""


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
    rejected: list[dict[str, str]] = []
    for server_name, server_cfg in servers.items():
        target_name = str(server_name)
        # These land in the global MCP config and are later executed, so the
        # shape is checked rather than trusted.
        problem = _mcp_server_problem(target_name, server_cfg)
        if problem:
            rejected.append({"server": target_name, "error": problem})
            continue
        if target_name in cfg["mcp"]["servers"] and not force:
            skipped.append(target_name)
            continue
        cfg["mcp"]["servers"][target_name] = server_cfg
        added.append(target_name)
    GLOBAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with GLOBAL_CONFIG.open("wb") as f:
        tomli_w.dump(cfg, f)
    return {
        "ok": True,
        "plugin": name,
        "added": added,
        "skipped": skipped,
        "rejected": rejected,
        "config": str(GLOBAL_CONFIG),
    }


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
    if ecosystem not in {"opencode", "claude", "codex-skill", "gemini", "pi"}:
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
    elif ecosystem == "pi":
        from magent.plugin_compat_pi import import_pi

        import_pi(src, target, converted)
    else:
        _import_codex_skill(src, target, converted)
    _copy_mcp_if_present(src, target, converted)
    if ecosystem == "pi":
        report_path = target / "compatibility" / "pi" / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["portable"]["mcp"] = list(converted.get("mcp", []))
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
    result = {
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
    pi_report = target / "compatibility" / "pi" / "report.json"
    if pi_report.is_file():
        result["compatibility_report"] = json.loads(pi_report.read_text(encoding="utf-8"))
    return result


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
    from magent.plugin_compat_pi import is_pi_package, pi_manifest

    package_pi = pi_manifest(path)
    pi_layout = any((path / item).exists() for item in ("extensions", "prompts", "themes", ".pi"))
    if is_pi_package(path) or pi_layout:
        compatibility.append("pi")
        if package_pi.get("skills") or (path / ".pi" / "skills").exists():
            capabilities.append("skills")
        if package_pi.get("prompts") or (path / ".pi" / "prompts").exists():
            capabilities.append("recipes")
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


def run_pi_plugin_bridge(
    name: str,
    *,
    project: str = ".",
    mode: str = "interactive",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Launch imported Pi extensions in Pi's own runtime after an explicit grant."""
    target_result = _plugin_target(name)
    if not target_result["ok"] or not target_result["path"].is_dir():
        return {"ok": False, "error": f"Plugin not installed: {name}"}
    state = _state()
    plugin_state = state.get(name, {})
    if not plugin_state.get("enabled"):
        return {"ok": False, "error": f"Plugin must be enabled before bridging: {name}"}
    project_path = Path(project).expanduser().resolve()
    grants = plugin_state.get("grants", {})
    granted = set(grants.get(str(project_path), [])) | set(grants.get("user", []))
    if "external_process" not in granted:
        return {
            "ok": False,
            "error": "Pi bridge requires an external_process grant at user or project scope.",
            "grant_command": f"magent plugin grant {name} --scope project --project {project_path} --permissions external_process",
        }
    if mode not in {"interactive", "rpc", "json"}:
        return {"ok": False, "error": "mode must be interactive, rpc, or json"}
    from magent.plugin_sdk import verify_plugin

    verification = verify_plugin(target_result["path"])
    if not verification.get("ok"):
        return {"ok": False, "error": "Plugin integrity check failed", "verification": verification}
    pi_executable = shutil.which("pi")
    if not pi_executable and not dry_run:
        return {"ok": False, "error": "Pi executable was not found on PATH"}
    pi_executable = pi_executable or "pi"

    compatibility_root = target_result["path"] / "compatibility" / "pi"
    report_path = compatibility_root / "report.json"
    if not report_path.is_file():
        return {"ok": False, "error": f"Plugin is not an imported Pi pack: {name}"}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"Unreadable Pi report for {name}: {exc}"}

    # Defensive .get() chains: direct indexing raised an uncaught KeyError on a
    # malformed report.
    preserved = (report or {}).get("preserved") or {}
    package_root = compatibility_root / "package"
    try:
        extensions = _contained_paths(package_root, preserved.get("extensions"), "extensions")
        themes = _contained_paths(package_root, preserved.get("themes"), "themes")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    skills = sorted((target_result["path"] / "skills").rglob("SKILL.md"))
    prompts = sorted((target_result["path"] / "recipes").glob("*.md"))
    command = [pi_executable, "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes"]
    for extension in extensions:
        command.extend(["--extension", str(extension)])
    for skill in skills:
        command.extend(["--skill", str(skill)])
    for prompt in prompts:
        command.extend(["--prompt-template", str(prompt)])
    for theme in themes:
        command.extend(["--theme", str(theme)])
    if mode != "interactive":
        command.extend(["--mode", mode])
    result = {
        "ok": True,
        "plugin": name,
        "project": str(project_path),
        "mode": mode,
        "command": command,
        "executed": False,
    }
    if dry_run:
        return result
    completed = subprocess.run(command, cwd=project_path, check=False)  # noqa: S603
    return {**result, "executed": True, "returncode": completed.returncode, "ok": completed.returncode == 0}


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
    normalized = {
        "api_version": "1",
        "version": "0.1.0",
        "magent": ">=0.34.0",
        **metadata,
    }
    with (path / "magent-plugin.toml").open("wb") as f:
        tomli_w.dump({"plugin": normalized}, f)
    from magent.plugin_sdk import plugin_digest

    normalized["checksum"] = plugin_digest(path)
    with (path / "magent-plugin.toml").open("wb") as f:
        tomli_w.dump({"plugin": normalized}, f)


def _write_mcp_servers(path: Path, servers: dict[str, Any]) -> None:
    import tomli_w

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump({"mcp": {"servers": servers}}, f)


def _infer_permissions(path: Path) -> list[str]:
    permissions = []
    if (path / "mcp.toml").exists() or _mcp_servers_from_source(path):
        permissions.extend(["external_process", "network"])
    if (path / "tools").exists():
        permissions.append("tools")
    report = path / "compatibility" / "pi" / "report.json"
    if report.is_file():
        try:
            if json.loads(report.read_text(encoding="utf-8")).get("preserved", {}).get("extensions"):
                permissions.append("external_process")
        except Exception:
            pass
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
