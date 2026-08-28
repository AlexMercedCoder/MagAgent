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
    validate_delta_document,
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


def make_delta(
    profile: Any, operations: list[dict[str, Any]], *, evidence: str = ""
) -> dict[str, Any]:
    safe = []
    for operation in operations:
        path = str(operation.get("path", ""))
        if not (path == "/state" or path.startswith("/state/")):
            raise ProfileError(f"operation path {path!r} is outside /state")
        safe.append(_scrub(dict(operation)))
    document = {
        "oap": "1.0",
        "kind": "AgentStateDelta",
        "target": {
            "name": profile.name,
            "revision": profile.revision,
            "digest": profile.profile_digest,
        },
        "session": {
            "id": "magent-" + uuid.uuid4().hex[:12],
            "harness": "magagent",
        },
        "operations": safe,
        **({"summary": scrub_secrets(evidence)} if evidence else {}),
    }
    validate_delta_document(document)
    return document


def rebase_delta(path: Path, delta: dict[str, Any]) -> dict[str, Any]:
    """Reject rebasing: portable deltas intentionally carry no private base snapshot."""
    document, _body, _encoding = parse_document(path)
    validate_document(document)
    raise ProfileConflictError(
        "canonical OAP deltas do not carry a base-state snapshot; regenerate the delta"
    )


def apply_delta(path: Path, delta: dict[str, Any], *, auto_rebase: bool = False) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileError("managed profiles cannot be modified")
    validate_delta_document(delta)
    document, _body, encoding = parse_document(path)
    validate_document(document)
    lifecycle = document.get("spec", {}).get("lifecycle", {})
    if lifecycle.get("writeback", "propose") == "off":
        raise ProfileError("profile lifecycle.writeback is off")
    revision = int(document.get("metadata", {}).get("revision", 1))
    actual = digest_document(document)
    target = delta.get("target", {})
    if revision != int(target.get("revision", 0)) or actual != target.get("digest"):
        if not auto_rebase:
            raise ProfileConflictError(
                f"profile changed since proposal: current r{revision}, delta targets r{target.get('revision')}"
            )
        delta = rebase_delta(path, delta)
        document, _body, encoding = parse_document(path)
        revision = int(document.get("metadata", {}).get("revision", 1))
    checkpoint = create_checkpoint(path, document, encoding)
    for operation in delta.get("operations", []):
        _apply_state_operation(document, operation)
    document.setdefault("metadata", {})["revision"] = revision + 1
    document["metadata"]["updated_at"] = _now()
    _enforce_canonical_retention(document)
    document.setdefault("history", []).append(
        {
            "revision": revision + 1,
            "at": _now(),
            "by": "magagent",
            "session_id": str(delta.get("session", {}).get("id", "")),
            "change": scrub_secrets(str(delta.get("summary", "State update"))),
            "sections": ["state"],
        }
    )
    max_history = int(lifecycle.get("retention", {}).get("max_history", 50))
    if max_history >= 0:
        document["history"] = document["history"][-max_history:] if max_history else []
    validate_document(document)
    atomic_write(path, render_document(document, encoding))
    return {
        "ok": True,
        "path": str(path),
        "revision": revision + 1,
        "profile_digest": digest_document(document),
        "checkpoint": str(checkpoint),
    }


def create_checkpoint(path: Path, document: dict[str, Any], encoding: str) -> Path:
    """Persist a restorable copy of a profile before a mutation."""
    directory = (
        path.parent.parent / "profile-checkpoints"
        if path.parent.name == "agents"
        else path.parent / ".profile-checkpoints"
    )
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
    safety = create_checkpoint(path, current, current_encoding)
    atomic_write(path, render_document(restored, restored_encoding))
    return {
        "ok": True,
        "path": str(path),
        "revision": restored.get("metadata", {}).get("revision", 1),
        "safety_checkpoint": str(safety),
    }


def _apply_state_operation(document: dict[str, Any], operation: dict[str, Any]) -> None:
    path = str(operation.get("path", ""))
    if not (path == "/state" or path.startswith("/state/")):
        raise ProfileError(f"operation path {path!r} is outside /state")
    action = str(operation.get("op", "replace"))
    value = _scrub(operation.get("value"))
    state = document.setdefault("state", {} if document.get("kind") == "AgentProfile" else [])
    if path == "/state":
        if action == "remove":
            document["state"] = []
        elif isinstance(value, (list, dict)):
            document["state"] = value
        else:
            raise ProfileError("/state replacement must be an array or object")
        return
    if isinstance(state, dict):
        _apply_canonical_state_operation(state, path, action, value)
        state["updated_at"] = _now()
        return
    if not isinstance(state, list):
        raise ProfileError("entry operations require state to be an array or canonical object")
    selector = path[len("/state/") :].replace("~1", "/").replace("~0", "~")
    if selector == "-":
        if action != "add":
            raise ProfileError("/state/- only supports add")
        state.append(value)
        return
    index = next(
        (
            i
            for i, item in enumerate(state)
            if isinstance(item, dict) and str(item.get("id")) == selector
        ),
        None,
    )
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


def _apply_canonical_state_operation(
    state: dict[str, Any], path: str, action: str, value: Any
) -> None:
    tokens = path.split("/")[2:]
    if not tokens:
        if action == "remove":
            state.clear()
        elif isinstance(value, dict):
            state.clear()
            state.update(value)
        else:
            raise ProfileError("canonical /state replacement must be an object")
        return
    collection = tokens[0]
    if collection not in {"facts", "preferences", "glossary", "open_threads"}:
        if action == "remove":
            state.pop(collection, None)
        else:
            state[collection] = value
        return
    entries = state.setdefault(collection, [])
    if not isinstance(entries, list):
        raise ProfileError(f"/state/{collection} is not an array")
    selector = tokens[1] if len(tokens) > 1 else "-"
    if selector.startswith("id:"):
        selector = selector[3:]
    if selector == "-":
        if action != "add":
            raise ProfileError(f"/state/{collection}/- only supports add")
        entries.append(value)
        return
    index = next(
        (
            i
            for i, item in enumerate(entries)
            if isinstance(item, dict) and item.get("id") == selector
        ),
        None,
    )
    if action == "remove":
        if index is not None:
            entries.pop(index)
    elif index is None:
        if action == "replace":
            raise ProfileError(f"state entry not found: {selector}")
        entries.append(value)
    else:
        entries[index] = value


def _enforce_canonical_retention(document: dict[str, Any]) -> None:
    state = document.get("state")
    if not isinstance(state, dict):
        return
    retention = document.get("spec", {}).get("lifecycle", {}).get("retention", {})
    limit = retention.get("max_facts")
    facts = state.get("facts")
    if not isinstance(limit, int) or not isinstance(facts, list) or len(facts) <= limit:
        return
    while len(facts) > limit:
        index = next(
            (
                i
                for i, item in enumerate(facts)
                if not isinstance(item, dict) or not item.get("pinned")
            ),
            None,
        )
        if index is None:
            raise ProfileError("pinned facts exceed lifecycle.retention.max_facts")
        facts.pop(index)


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
        item = {
            "id": delta.get("session", {}).get("id"),
            "delta": delta,
            "status": "pending",
            "created_at": _now(),
        }
        items.append(item)
        self.write(items)
        return item

    def pending(self) -> list[dict[str, Any]]:
        return [item for item in self.read() if item.get("status") == "pending"]

    def decide(
        self,
        delta_id: str,
        status: str,
        reason: str = "",
        *,
        auto_rebase: bool = True,
    ) -> dict[str, Any]:
        items = self.read()
        item = next((entry for entry in items if entry.get("id") == delta_id), None)
        if not item:
            raise ProfileError(f"profile delta not found: {delta_id}")
        if status == "accepted":
            delta = item.get("delta", {})
            name = str(delta.get("target", {}).get("name", ""))
            candidates = [
                self.root / ".magent" / "agents" / f"{name}.md",
                self.root / ".agents" / f"{name}.md",
                self.root / ".agents" / f"{name}.agent.yaml",
            ]
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is None:
                raise ProfileError(f"profile file not found for delta target: {name}")
            item["applied"] = apply_delta(
                path,
                delta,
                auto_rebase=auto_rebase,
            )
        item.update({"status": status, "reason": reason, "decided_at": _now()})
        self.write(items)
        return item
