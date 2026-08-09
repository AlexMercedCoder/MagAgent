"""Versioned plugin contracts, integrity checks, and local grant metadata."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

PLUGIN_API_VERSION = "1"
KNOWN_CAPABILITIES = frozenset({"agents", "skills", "recipes", "hooks", "tools", "mcp", "ui"})
KNOWN_PERMISSIONS = frozenset(
    {"files", "shell", "web", "data", "db", "desktop", "external_process", "network", "tools"}
)
MAX_PLUGIN_FILE_BYTES = 5 * 1024 * 1024

MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/AlexMercedCoder/MagAgent/schemas/magent-plugin-v1.json",
    "title": "MagAgent Plugin Manifest v1",
    "type": "object",
    "required": ["name", "version", "api_version"],
    "properties": {
        "name": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"},
        "version": {"type": "string", "minLength": 1},
        "api_version": {"const": PLUGIN_API_VERSION},
        "description": {"type": "string"},
        "source_url": {"type": "string"},
        "magent": {"type": "string", "description": "Compatible MagAgent version range."},
        "capabilities": {"type": "array", "items": {"enum": sorted(KNOWN_CAPABILITIES)}},
        "permissions": {"type": "array", "items": {"enum": sorted(KNOWN_PERMISSIONS)}},
        "compatibility": {"type": "array", "items": {"type": "string"}},
        "trust": {"enum": ["untrusted", "local", "reviewed", "verified"]},
        "checksum": {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"},
        "signature": {"type": "string"},
        "maintainers": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}


def validate_plugin(path: str | Path, *, strict: bool = True) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        return {"ok": False, "path": str(root), "errors": ["Plugin directory does not exist"], "warnings": []}
    manifest = _manifest(root)
    _validate_manifest(manifest, errors, warnings, strict=strict)
    files = _plugin_files(root, errors)
    contributions = _contributions(root, errors, warnings)
    inferred_permissions = _infer_permissions(root)
    declared_permissions = set(_strings(manifest.get("permissions")))
    missing_permissions = sorted(inferred_permissions - declared_permissions)
    if missing_permissions:
        message = f"Manifest does not declare inferred permissions: {', '.join(missing_permissions)}"
        (errors if strict else warnings).append(message)
    digest = plugin_digest(root)
    expected = str(manifest.get("checksum") or "")
    if expected and expected != digest:
        errors.append(f"Checksum mismatch: expected {expected}, calculated {digest}")
    return {
        "ok": not errors,
        "schema": "magent.plugin-report.v1",
        "api_version": PLUGIN_API_VERSION,
        "path": str(root),
        "manifest": manifest,
        "digest": digest,
        "files": files,
        "contributions": contributions,
        "inferred_permissions": sorted(inferred_permissions),
        "errors": errors,
        "warnings": warnings,
    }


def verify_plugin(path: str | Path) -> dict[str, Any]:
    report = validate_plugin(path, strict=False)
    manifest = report.get("manifest", {})
    expected = str(manifest.get("checksum") or "")
    report["integrity"] = "verified" if expected and expected == report.get("digest") else "unrecorded"
    report["ok"] = bool(report.get("ok")) and (not expected or report["integrity"] == "verified")
    return report


def plugin_digest(path: str | Path) -> str:
    root = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    for file in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "magent-plugin.toml"):
        relative = file.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def build_registry_index(paths: list[str | Path]) -> dict[str, Any]:
    plugins = []
    for path in paths:
        report = validate_plugin(path, strict=False)
        manifest = report.get("manifest", {})
        plugins.append(
            {
                "name": manifest.get("name", Path(path).name),
                "version": manifest.get("version", ""),
                "api_version": manifest.get("api_version", ""),
                "source_url": manifest.get("source_url", ""),
                "magent": manifest.get("magent", ""),
                "capabilities": manifest.get("capabilities", []),
                "permissions": manifest.get("permissions", []),
                "trust": manifest.get("trust", "untrusted"),
                "digest": report.get("digest", ""),
                "valid": report.get("ok", False),
            }
        )
    return {"schema": "magent.plugin-registry.v1", "plugins": sorted(plugins, key=lambda item: (item["name"], item["version"]))}


def write_schema(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(MANIFEST_SCHEMA, indent=2) + "\n", encoding="utf-8")
    return target


def _manifest(root: Path) -> dict[str, Any]:
    path = root / "magent-plugin.toml"
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        return dict(data.get("plugin", data))
    except Exception:
        return {}


def _validate_manifest(manifest: dict[str, Any], errors: list[str], warnings: list[str], *, strict: bool) -> None:
    if not manifest:
        (errors if strict else warnings).append("magent-plugin.toml is missing or invalid")
        return
    for field in ("name", "version", "api_version"):
        if not str(manifest.get(field) or "").strip():
            (errors if strict else warnings).append(f"Manifest field is required: {field}")
    if manifest.get("api_version") not in {None, "", PLUGIN_API_VERSION, int(PLUGIN_API_VERSION)}:
        errors.append(f"Unsupported plugin api_version: {manifest.get('api_version')}")
    unknown_capabilities = sorted(set(_strings(manifest.get("capabilities"))) - KNOWN_CAPABILITIES)
    unknown_permissions = sorted(set(_strings(manifest.get("permissions"))) - KNOWN_PERMISSIONS)
    if unknown_capabilities:
        errors.append(f"Unknown capabilities: {', '.join(unknown_capabilities)}")
    if unknown_permissions:
        errors.append(f"Unknown permissions: {', '.join(unknown_permissions)}")
    if manifest.get("signature") and not manifest.get("checksum"):
        errors.append("A signed plugin must declare its checksum")
    if not manifest.get("signature"):
        warnings.append("Plugin is unsigned")


def _plugin_files(root: Path, errors: list[str]) -> list[dict[str, Any]]:
    files = []
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            errors.append(f"Symbolic links are not allowed in plugin packs: {item.relative_to(root)}")
            continue
        if not item.is_file():
            continue
        size = item.stat().st_size
        if size > MAX_PLUGIN_FILE_BYTES:
            errors.append(f"Plugin file exceeds {MAX_PLUGIN_FILE_BYTES} bytes: {item.relative_to(root)}")
        files.append({"path": item.relative_to(root).as_posix(), "bytes": size})
    return files


def _contributions(root: Path, errors: list[str], warnings: list[str]) -> dict[str, list[str]]:
    contributions: dict[str, list[str]] = {}
    for kind, directory in (("agents", root / "agents"), ("skills", root / "skills"), ("recipes", root / "recipes")):
        if not directory.exists():
            continue
        items = [item.relative_to(root).as_posix() for item in directory.rglob("*.md") if item.is_file()]
        if kind == "skills":
            items.extend(item.relative_to(root).as_posix() for item in directory.rglob("SKILL.md") if item.is_file() and item.relative_to(root).as_posix() not in items)
        contributions[kind] = sorted(set(items))
        if not contributions[kind]:
            warnings.append(f"{kind}/ exists but contains no Markdown contributions")
    hooks = root / "hooks.toml"
    if hooks.exists():
        try:
            with hooks.open("rb") as handle:
                tomllib.load(handle)
            contributions["hooks"] = ["hooks.toml"]
        except Exception as exc:
            errors.append(f"Invalid hooks.toml: {exc}")
    mcp = root / "mcp.toml"
    if mcp.exists():
        try:
            with mcp.open("rb") as handle:
                data = tomllib.load(handle)
            servers = data.get("mcp", {}).get("servers", {})
            if not isinstance(servers, dict) or not servers:
                errors.append("mcp.toml must declare at least one [mcp.servers.*] table")
            contributions["mcp"] = sorted(str(item) for item in servers)
        except Exception as exc:
            errors.append(f"Invalid mcp.toml: {exc}")
    return contributions


def _infer_permissions(root: Path) -> set[str]:
    permissions: set[str] = set()
    if (root / "mcp.toml").exists():
        permissions.update({"external_process", "network"})
    if (root / "tools").exists() or (root / "hooks.toml").exists():
        permissions.add("tools")
    return permissions


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    return [str(value)]
