"""Reviewable, conflict-safe OAP state deltas."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent.agent_profiles.digest import digest_document
from magent.agent_profiles.documents import (
    atomic_write,
    parse_document,
    render_document,
    validate_document,
)
from magent.agent_profiles.errors import ProfileConflictError, ProfileError
from magent.secret_scrub import scrub_secrets


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_secrets(value)
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _scrub(item) for key, item in value.items()}
    return value


def make_delta(profile: Any, operations: list[dict[str, Any]], *, evidence: str = "") -> dict[str, Any]:
    safe = []
    for operation in operations:
        path = str(operation.get("path", ""))
        if not (path == "/state" or path.startswith("/state/")):
            raise ProfileError(f"operation path {path!r} is outside /state")
        safe.append(_scrub(dict(operation)))
    return {
        "id": "oap_delta_" + uuid.uuid4().hex[:12],
        "kind": "agent_profile_delta",
        "profile": profile.name,
        "profile_path": str(profile.source_path or ""),
        "base_revision": profile.revision,
        "base_digest": profile.profile_digest,
        "operations": safe,
        "evidence": scrub_secrets(evidence),
        "status": "pending",
        "created_at": _now(),
    }


def apply_delta(path: Path, delta: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileError("managed profiles cannot be modified")
    document, _body, encoding = parse_document(path)
    validate_document(document)
    revision = int(document.get("metadata", {}).get("revision", 1))
    if revision != int(delta.get("base_revision", 0)):
        raise ProfileConflictError(f"revision conflict: profile is r{revision}, delta targets r{delta.get('base_revision')}")
    actual = digest_document(document)
    if actual != delta.get("base_digest"):
        raise ProfileConflictError("profile digest changed since the delta was proposed")
    checkpoint = _checkpoint(path, document, encoding)
    for operation in delta.get("operations", []):
        _apply_state_operation(document, operation)
    document.setdefault("metadata", {})["revision"] = revision + 1
    document.setdefault("history", []).append({
        "revision": revision + 1,
        "at": _now(),
        "delta": str(delta.get("id", "")),
        "evidence": scrub_secrets(str(delta.get("evidence", ""))),
    })
    validate_document(document)
    atomic_write(path, render_document(document, encoding))
    return {"ok": True, "path": str(path), "revision": revision + 1, "profile_digest": digest_document(document), "checkpoint": str(checkpoint)}


def _checkpoint(path: Path, document: dict[str, Any], encoding: str) -> Path:
    directory = path.parent.parent / "profile-checkpoints" if path.parent.name == "agents" else path.parent / ".profile-checkpoints"
    name = str(document.get("metadata", {}).get("name", path.stem))
    revision = int(document.get("metadata", {}).get("revision", 1))
    digest = digest_document(document).split(":", 1)[-1][:12]
    target = directory / f"{name}-r{revision}-{digest}{path.suffix}.bak"
    atomic_write(target, render_document(document, encoding))
    return target


def restore_checkpoint(path: Path, checkpoint: Path) -> dict[str, Any]:
    """Restore a validated profile checkpoint with a checkpoint of current state."""
    current, _body, current_encoding = parse_document(path)
    restored, _restored_body, restored_encoding = parse_document(checkpoint)
    validate_document(current)
    validate_document(restored)
    safety = _checkpoint(path, current, current_encoding)
    atomic_write(path, render_document(restored, restored_encoding))
    return {"ok": True, "path": str(path), "revision": restored.get("metadata", {}).get("revision", 1), "safety_checkpoint": str(safety)}


def _apply_state_operation(document: dict[str, Any], operation: dict[str, Any]) -> None:
    path = str(operation.get("path", ""))
    if not (path == "/state" or path.startswith("/state/")):
        raise ProfileError(f"operation path {path!r} is outside /state")
    action = str(operation.get("op", "replace"))
    value = _scrub(operation.get("value"))
    state = document.setdefault("state", [])
    if path == "/state":
        if action == "remove":
            document["state"] = []
        elif isinstance(value, (list, dict)):
            document["state"] = value
        else:
            raise ProfileError("/state replacement must be an array or object")
        return
    if not isinstance(state, list):
        raise ProfileError("entry operations require state to be an array")
    selector = path[len("/state/") :].replace("~1", "/").replace("~0", "~")
    if selector == "-":
        if action != "add":
            raise ProfileError("/state/- only supports add")
        state.append(value)
        return
    index = next((i for i, item in enumerate(state) if isinstance(item, dict) and str(item.get("id")) == selector), None)
    if action == "remove":
        if index is None:
            raise ProfileError(f"state entry not found: {selector}")
        state.pop(index)
    elif index is None:
        if not isinstance(value, dict):
            value = {"id": selector, "content": str(value)}
        value.setdefault("id", selector)
        state.append(value)
    else:
        state[index] = value


class ProfileDeltaInbox:
    def __init__(self, project: str | Path = "."):
        self.root = Path(project).resolve()
        self.path = self.root / ".magent" / "agent-profile-inbox.json"

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []

    def write(self, items: list[dict[str, Any]]) -> None:
        atomic_write(self.path, json.dumps(items, indent=2, ensure_ascii=False) + "\n")

    def add(self, delta: dict[str, Any]) -> dict[str, Any]:
        items = self.read()
        items.append(delta)
        self.write(items)
        return delta

    def pending(self) -> list[dict[str, Any]]:
        return [item for item in self.read() if item.get("status") == "pending"]

    def decide(self, delta_id: str, status: str, reason: str = "") -> dict[str, Any]:
        items = self.read()
        item = next((entry for entry in items if entry.get("id") == delta_id), None)
        if not item:
            raise ProfileError(f"profile delta not found: {delta_id}")
        if status == "accepted":
            apply_delta(Path(str(item.get("profile_path", ""))), item)
        item.update({"status": status, "reason": reason, "decided_at": _now()})
        self.write(items)
        return item
