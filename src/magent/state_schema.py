"""Version marker and downgrade protection for persistent MagAgent state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from magent import __version__

STATE_SCHEMA_VERSION = 1
STATE_MANIFEST = "state.json"


class StateCompatibilityError(RuntimeError):
    """Raised when an older runtime would open newer persistent state."""


def state_manifest(root: str | Path) -> dict[str, Any]:
    path = Path(root) / STATE_MANIFEST
    if not path.exists():
        return {"schema_version": 0, "magent_version": "legacy", "path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateCompatibilityError(
            f"Could not read MagAgent state marker {path}: {exc}"
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("schema_version"), int):
        raise StateCompatibilityError(f"Invalid MagAgent state marker: {path}")
    return {**value, "path": str(path)}


def assert_supported_state(root: str | Path) -> dict[str, Any]:
    manifest = state_manifest(root)
    version = int(manifest["schema_version"])
    if version > STATE_SCHEMA_VERSION:
        raise StateCompatibilityError(
            f"State schema {version} is newer than this MagAgent supports "
            f"({STATE_SCHEMA_VERSION}). Upgrade MagAgent or restore a compatible backup; "
            "opening newer state with an older runtime is refused."
        )
    return manifest


def write_state_manifest(root: str | Path, *, migrated_from: int = 0) -> Path:
    directory = Path(root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / STATE_MANIFEST
    payload = {
        "schema": "magent.state.v1",
        "schema_version": STATE_SCHEMA_VERSION,
        "magent_version": __version__,
        "migrated_from": migrated_from,
    }
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return target
