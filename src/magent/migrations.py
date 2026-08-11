"""Backup-first persistent-state migration and rollback services."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import tomli_w

from magent import __version__
from magent.state_schema import (
    STATE_MANIFEST,
    STATE_SCHEMA_VERSION,
    StateCompatibilityError,
    assert_supported_state,
    state_manifest,
    write_state_manifest,
)

SCHEMA = "magent.migration.v1"
BACKUP_DIRNAME = "migration-backups"


def migration_plan(root: str | Path) -> dict[str, Any]:
    directory = Path(root).resolve()
    try:
        manifest = assert_supported_state(directory)
    except StateCompatibilityError as exc:
        return {
            "ok": False,
            "schema": SCHEMA,
            "root": str(directory),
            "current_schema": state_manifest(directory).get("schema_version"),
            "target_schema": STATE_SCHEMA_VERSION,
            "status": "downgrade-refused",
            "error": str(exc),
            "changes": [],
        }
    current = int(manifest["schema_version"])
    changes: list[str] = []
    if current < 1:
        changes.append("Create the magent.state.v1 persistent-state marker.")
        changes.extend(_legacy_config_changes(directory))
    return {
        "ok": True,
        "schema": SCHEMA,
        "root": str(directory),
        "current_schema": current,
        "target_schema": STATE_SCHEMA_VERSION,
        "status": "current" if current == STATE_SCHEMA_VERSION else "upgrade-ready",
        "backup_required": bool(changes),
        "changes": changes,
    }


def migration_assurance_report() -> dict[str, Any]:
    """Exercise legacy upgrade, rollback, and future-schema refusal in isolation."""
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="magent-migration-assurance-") as temporary:
        root = Path(temporary)
        profile = root / "users" / "legacy" / "profile.toml"
        profile.parent.mkdir(parents=True)
        (root / "config.toml").write_text("[agent]\nmax_subagents = 4\n", encoding="utf-8")
        profile.write_text(
            '[permissions]\nallowed_commands = ["git *", "pytest *"]\n', encoding="utf-8"
        )
        migrated = migrate_state(root, apply=True)
        config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
        migrated_profile = tomllib.loads(profile.read_text(encoding="utf-8"))
        checks["legacy-upgrade"] = bool(
            migrated.get("ok")
            and migrated.get("applied")
            and config.get("subagents", {}).get("max_subagents") == 4
            and "allowed_shell_patterns" in migrated_profile.get("permissions", {})
        )
        backup = str(migrated.get("backup", ""))
        rolled_back = rollback_state(root, backup, apply=True)
        checks["rollback"] = bool(
            rolled_back.get("ok")
            and "allowed_commands"
            in tomllib.loads(profile.read_text(encoding="utf-8")).get("permissions", {})
        )
        (root / STATE_MANIFEST).write_text(
            json.dumps({"schema_version": STATE_SCHEMA_VERSION + 1}), encoding="utf-8"
        )
        future = migration_plan(root)
        checks["downgrade-refusal"] = bool(
            not future.get("ok") and future.get("status") == "downgrade-refused"
        )
    return {
        "ok": all(checks.values()),
        "schema": "magent.migration-assurance.v1",
        "state_schema": STATE_SCHEMA_VERSION,
        "checks": checks,
    }


def migrate_state(
    root: str | Path,
    *,
    apply: bool = False,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    directory = Path(root).resolve()
    plan = migration_plan(directory)
    if not plan["ok"] or not apply or plan["status"] == "current":
        return {**plan, "applied": False, "backup": ""}

    backup = create_state_backup(directory, backup_dir=backup_dir)
    changed = _migrate_legacy_configs(directory)
    write_state_manifest(directory, migrated_from=int(plan["current_schema"]))
    history = directory / "migration-history.json"
    records = _read_json_list(history)
    records.append(
        {
            "schema": SCHEMA,
            "from": plan["current_schema"],
            "to": STATE_SCHEMA_VERSION,
            "magent_version": __version__,
            "applied_at": datetime.now(UTC).isoformat(),
            "backup": str(backup),
            "changed": changed,
        }
    )
    _atomic_json(history, records)
    return {
        **migration_plan(directory),
        "applied": True,
        "backup": str(backup),
        "backup_sha256": _sha256(backup),
        "changed": changed,
    }


def create_state_backup(
    root: str | Path,
    *,
    backup_dir: str | Path | None = None,
) -> Path:
    directory = Path(root).resolve()
    destination = Path(backup_dir).resolve() if backup_dir else directory / BACKUP_DIRNAME
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = destination / f"magent-state-{stamp}.zip"
    suffix = 1
    while target.exists():
        target = destination / f"magent-state-{stamp}-{suffix}.zip"
        suffix += 1
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or destination in path.parents:
                continue
            relative = path.relative_to(directory)
            archive.write(path, relative.as_posix())
    os.chmod(target, 0o600)
    return target


def rollback_state(root: str | Path, backup: str | Path, *, apply: bool = False) -> dict[str, Any]:
    directory = Path(root).resolve()
    source = Path(backup).resolve()
    members = inspect_state_backup(source)
    if not apply:
        return {
            "ok": True,
            "schema": SCHEMA,
            "applied": False,
            "root": str(directory),
            "backup": str(source),
            "files": members,
        }
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        for name in members:
            target = (directory / name).resolve()
            if directory not in target.parents and target != directory:
                raise StateCompatibilityError(f"Unsafe backup member: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as reader, target.open("wb") as writer:
                shutil.copyfileobj(reader, writer)
    marker = directory / STATE_MANIFEST
    if STATE_MANIFEST not in members and marker.exists():
        marker.unlink()
    return {
        "ok": True,
        "schema": SCHEMA,
        "applied": True,
        "root": str(directory),
        "backup": str(source),
        "files": members,
    }


def inspect_state_backup(path: str | Path) -> list[str]:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
    for name in names:
        candidate = PurePosixPath(name)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise StateCompatibilityError(f"Unsafe backup member: {name}")
    return names


def _legacy_config_changes(root: Path) -> list[str]:
    changes: list[str] = []
    global_config = root / "config.toml"
    if _toml_has(global_config, "agent", "max_subagents"):
        changes.append("Copy agent.max_subagents to subagents.max_subagents.")
    users = root / "users"
    for profile in sorted(users.glob("*/profile.toml")) if users.exists() else []:
        if _toml_has(profile, "permissions", "allowed_commands"):
            changes.append(
                f"Rename {profile.relative_to(root)} permissions.allowed_commands "
                "to permissions.allowed_shell_patterns."
            )
    return changes


def _migrate_legacy_configs(root: Path) -> list[str]:
    changed: list[str] = []
    global_config = root / "config.toml"
    if global_config.exists():
        data = tomllib.loads(global_config.read_text(encoding="utf-8"))
        legacy = data.get("agent", {}).get("max_subagents")
        if legacy is not None and "max_subagents" not in data.get("subagents", {}):
            data.setdefault("subagents", {})["max_subagents"] = legacy
            _atomic_toml(global_config, data)
            changed.append(str(global_config.relative_to(root)))
    users = root / "users"
    for profile in sorted(users.glob("*/profile.toml")) if users.exists() else []:
        data = tomllib.loads(profile.read_text(encoding="utf-8"))
        permissions = data.get("permissions", {})
        if "allowed_commands" in permissions and "allowed_shell_patterns" not in permissions:
            permissions["allowed_shell_patterns"] = permissions.pop("allowed_commands")
            _atomic_toml(profile, data)
            changed.append(str(profile.relative_to(root)))
    return changed


def _toml_has(path: Path, section: str, key: str) -> bool:
    if not path.exists():
        return False
    try:
        return key in tomllib.loads(path.read_text(encoding="utf-8")).get(section, {})
    except (OSError, tomllib.TOMLDecodeError):
        return False


def _atomic_toml(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(tomli_w.dumps(value), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
