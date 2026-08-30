"""Durable conversation records for the bundled local Web UI."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent.workbench_store import WorkbenchStore

CONVERSATION_KINDS = {"chat", "bot", "group"}
MAX_GROUP_PARTICIPANTS = 5
PERMISSION_MODES = {"paranoid", "balanced", "silent", "yolo"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ConversationStore:
    """Small metadata/message layer backed by the existing atomic workbench store."""

    collection = "web_conversations"

    def __init__(self, store: WorkbenchStore):
        self.store = store

    def list(self, *, include_archived: bool = False) -> builtins.list[dict[str, Any]]:
        records = self.store.read(self.collection, [])
        if not include_archived:
            records = [item for item in records if not item.get("archived")]
        return sorted(records, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.store.read(self.collection, [])
                if item.get("id") == conversation_id
            ),
            None,
        )

    def create(
        self,
        *,
        title: str = "New conversation",
        kind: str = "chat",
        project: str,
        profiles: builtins.list[str] | None = None,
        coordinator: str = "",
        permission_mode: str = "balanced",
    ) -> dict[str, Any]:
        kind = kind.strip().lower()
        if kind not in CONVERSATION_KINDS:
            raise ValueError(f"kind must be one of {', '.join(sorted(CONVERSATION_KINDS))}")
        selected = list(
            dict.fromkeys(str(item).strip() for item in (profiles or []) if str(item).strip())
        )
        if kind == "bot" and len(selected) != 1:
            raise ValueError("bot conversations require exactly one profile")
        if kind == "group":
            if not 2 <= len(selected) <= MAX_GROUP_PARTICIPANTS:
                raise ValueError("group conversations require 2 to 5 profiles")
            if coordinator not in selected:
                raise ValueError("the coordinator must be one of the group profiles")
        permission_mode = permission_mode.strip().lower()
        if permission_mode not in PERMISSION_MODES:
            raise ValueError(
                "permission mode must be one of " + ", ".join(sorted(PERMISSION_MODES))
            )
        now = _now()
        return self.store.append(
            self.collection,
            {
                "schema": "magent.web-conversation.v1",
                "title": title.strip()[:100] or "New conversation",
                "kind": kind,
                "project": project,
                "profiles": selected,
                "coordinator": coordinator if kind == "group" else "",
                "permission_mode": permission_mode,
                "messages": [],
                "archived": False,
                "updated_at": now,
            },
        )

    def update(self, conversation_id: str, **updates: Any) -> dict[str, Any]:
        allowed = {
            "title",
            "archived",
            "project",
            "profiles",
            "coordinator",
            "kind",
            "permission_mode",
        }
        safe = {key: value for key, value in updates.items() if key in allowed}
        if "title" in safe:
            safe["title"] = str(safe["title"]).strip()[:100] or "New conversation"
        if "project" in safe:
            safe["project"] = str(safe["project"]).strip()
        if "profiles" in safe:
            safe["profiles"] = list(
                dict.fromkeys(
                    str(item).strip() for item in (safe["profiles"] or []) if str(item).strip()
                )
            )
        if "permission_mode" in safe:
            mode = str(safe["permission_mode"] or "").strip().lower()
            if mode not in PERMISSION_MODES:
                raise ValueError(
                    "permission mode must be one of " + ", ".join(sorted(PERMISSION_MODES))
                )
            safe["permission_mode"] = mode
        record = self.store.update_item(self.collection, conversation_id, **safe)
        if record is None:
            raise KeyError("conversation not found")
        return record

    def delete(self, conversation_id: str) -> bool:
        """Permanently remove one conversation and its transcript."""

        def change(
            records: builtins.list[dict[str, Any]],
        ) -> tuple[builtins.list[dict[str, Any]], bool]:
            kept = [item for item in records if item.get("id") != conversation_id]
            return kept, len(kept) != len(records)

        return bool(self.store.mutate(self.collection, [], change))

    def append_message(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        speaker: str = "",
        status: str = "complete",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("invalid message role")
        message = {
            "id": f"msg_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
            "role": role,
            "content": str(content),
            "speaker": str(speaker),
            "status": status,
            "created_at": _now(),
            "metadata": metadata or {},
        }

        def change(
            records: builtins.list[dict[str, Any]],
        ) -> tuple[builtins.list[dict[str, Any]], dict[str, Any]]:
            for record in records:
                if record.get("id") == conversation_id:
                    record.setdefault("messages", []).append(message)
                    record["messages"] = record["messages"][-400:]
                    record["updated_at"] = message["created_at"]
                    return records, message
            raise KeyError("conversation not found")

        return self.store.mutate(self.collection, [], change)


def folder_catalog(raw_path: str = "", *, project: str | Path = ".") -> dict[str, Any]:
    """Return a bounded, directory-only listing for the local folder picker.

    Selecting a project already permits an arbitrary existing local directory;
    this endpoint only replaces error-prone path typing with an authenticated
    browser. Files and their contents are never returned.
    """

    home = Path.home().resolve()
    current = Path(raw_path).expanduser().resolve() if raw_path.strip() else home
    if not current.is_dir():
        raise ValueError("Choose an existing folder to browse.")
    try:
        children = sorted(
            (
                {"name": item.name, "path": str(item.resolve())}
                for item in current.iterdir()
                if item.is_dir()
            ),
            key=lambda item: item["name"].casefold(),
        )[:300]
    except PermissionError as error:
        raise ValueError("That folder cannot be opened with your current permissions.") from error
    roots: list[dict[str, str]] = []
    for label, value in (("Home", home), ("UI project", Path(project).resolve())):
        if str(value) not in {item["path"] for item in roots}:
            roots.append({"name": label, "path": str(value)})
    return {
        "ok": True,
        "path": str(current),
        "parent": str(current.parent) if current.parent != current else "",
        "directories": children,
        "roots": roots,
    }
