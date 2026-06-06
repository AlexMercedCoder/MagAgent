"""Config inspection, backup, diff, and restore helpers."""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path
from typing import Any

from magent.config import CONFIG_DIR, GLOBAL_CONFIG, get_current_user
from magent.workbench_store import now_iso

BACKUP_DIR = CONFIG_DIR / "backups"


def config_paths(username: str | None = None) -> dict[str, str]:
    username = username or get_current_user()
    paths = {"global": str(GLOBAL_CONFIG)}
    if username:
        paths["user"] = str(CONFIG_DIR / "users" / username / "profile.toml")
    return paths


def show_config(username: str | None = None) -> dict[str, Any]:
    """Return config file paths and text for global/current-user config."""
    result = {"ok": True, "files": {}}
    for key, raw_path in config_paths(username).items():
        path = Path(raw_path)
        result["files"][key] = {
            "path": str(path),
            "exists": path.exists(),
            "text": path.read_text(encoding="utf-8") if path.exists() else "",
        }
    return result


def backup_config(username: str | None = None) -> dict[str, Any]:
    """Copy global/current-user config files into a timestamped backup directory."""
    backup_id = now_iso().replace(":", "").replace("-", "").replace(".", "")
    target = BACKUP_DIR / backup_id
    target.mkdir(parents=True, exist_ok=True)
    copied = {}
    for key, raw_path in config_paths(username).items():
        path = Path(raw_path)
        if path.exists():
            dest = target / f"{key}.toml"
            shutil.copy2(path, dest)
            copied[key] = str(dest)
    manifest = {"id": backup_id, "files": copied}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"ok": True, "backup_id": backup_id, "path": str(target), "files": copied}


def list_config_backups() -> dict[str, Any]:
    """List config backup manifests."""
    backups = []
    if BACKUP_DIR.exists():
        for path in sorted(BACKUP_DIR.iterdir(), reverse=True):
            manifest = path / "manifest.json"
            if manifest.exists():
                backups.append(json.loads(manifest.read_text(encoding="utf-8")))
    return {"ok": True, "backups": backups}


def diff_config(backup_id: str | None = None, username: str | None = None) -> dict[str, Any]:
    """Return unified diffs between current config and a backup."""
    backup = _resolve_backup(backup_id)
    if not backup:
        return {"ok": False, "error": "No config backup found"}
    diffs = {}
    for key, raw_path in config_paths(username).items():
        current = Path(raw_path)
        old = backup / f"{key}.toml"
        before = old.read_text(encoding="utf-8").splitlines(keepends=True) if old.exists() else []
        after = current.read_text(encoding="utf-8").splitlines(keepends=True) if current.exists() else []
        diffs[key] = "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=str(old),
                tofile=str(current),
            )
        )
    return {"ok": True, "backup_id": backup.name, "diffs": diffs}


def restore_config(backup_id: str, username: str | None = None) -> dict[str, Any]:
    """Restore global/current-user config from a backup."""
    backup = _resolve_backup(backup_id)
    if not backup:
        return {"ok": False, "error": f"Config backup not found: {backup_id}"}
    restored = {}
    for key, raw_path in config_paths(username).items():
        source = backup / f"{key}.toml"
        dest = Path(raw_path)
        if source.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            restored[key] = str(dest)
    return {"ok": True, "backup_id": backup.name, "restored": restored}


def _resolve_backup(backup_id: str | None = None) -> Path | None:
    if backup_id:
        path = BACKUP_DIR / backup_id
        return path if path.exists() else None
    if not BACKUP_DIR.exists():
        return None
    backups = sorted((path for path in BACKUP_DIR.iterdir() if path.is_dir()), reverse=True)
    return backups[0] if backups else None
