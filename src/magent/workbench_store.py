"""JSON-backed workbench storage primitives."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from magent.config import USERS_DIR

WORKBENCH_DIRNAME = "workbench"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class WorkbenchStore:
    """Simple JSON-backed store scoped to one MagAgent user."""

    def __init__(self, username: str):
        self.username = username
        self.root = USERS_DIR / username / WORKBENCH_DIRNAME
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, default: Any) -> Any:
        path = self.root / f"{name}.json"
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def write(self, name: str, data: Any) -> None:
        path = self.root / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def append(self, name: str, item: dict[str, Any]) -> dict[str, Any]:
        data = self.read(name, [])
        next_id = _next_id(data, name.rstrip("s"))
        item = {"id": next_id, "created_at": now_iso(), **item}
        data.append(item)
        self.write(name, data)
        return item

    def update_item(self, name: str, item_id: str, **updates: Any) -> dict[str, Any] | None:
        data = self.read(name, [])
        for item in data:
            if item.get("id") == item_id:
                item.update(updates)
                item["updated_at"] = now_iso()
                self.write(name, data)
                return item
        return None


def _next_id(items: list[dict[str, Any]], prefix: str) -> str:
    existing = [
        int(str(item.get("id", "")).rsplit("_", 1)[-1])
        for item in items
        if str(item.get("id", "")).rsplit("_", 1)[-1].isdigit()
    ]
    return f"{prefix}_{(max(existing) if existing else 0) + 1:04d}"
