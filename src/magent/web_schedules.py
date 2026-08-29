"""Small durable interval scheduler for governed Web UI graph runs."""

from __future__ import annotations

import builtins
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class ScheduleStore:
    def __init__(self, store: Any, graph_runs: Any, project: str | Path):
        self.store = store
        self.graph_runs = graph_runs
        self.project = str(Path(project).resolve())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def list(self) -> dict[str, Any]:
        items = [
            item
            for item in self.store.read("web_schedules", [])
            if item.get("project") == self.project
        ]
        return {
            "ok": True,
            "schedules": sorted(items, key=lambda item: item.get("created_at", ""), reverse=True),
        }

    def create(
        self,
        path: str,
        interval_minutes: int,
        *,
        params: dict[str, Any] | None = None,
        approved_gates: builtins.list[str] | None = None,
    ) -> dict[str, Any]:
        interval = int(interval_minutes)
        if interval < 1 or interval > 525600:
            raise ValueError("interval must be between 1 minute and 1 year")
        # Preview applies graph path confinement and validates the plan before
        # anything durable is registered.
        self.graph_runs.preview(path)
        now = time.time()
        item = {
            "id": f"schedule_{uuid.uuid4().hex[:16]}",
            "path": path,
            "project": self.project,
            "interval_minutes": interval,
            "params": dict(params or {}),
            "approved_gates": [str(value) for value in approved_gates or []],
            "status": "active",
            "created_at": now,
            "next_run_at": now + interval * 60,
            "last_run_at": None,
            "last_job_id": "",
            "last_error": "",
        }
        self.store.mutate("web_schedules", [], lambda items: ([*items, item], None))
        return {"ok": True, "schedule": item}

    def action(self, schedule_id: str, action: str) -> dict[str, Any]:
        if action not in {"pause", "resume", "delete", "run"}:
            raise ValueError("unsupported schedule action")
        result: dict[str, Any] | None = None

        def change(
            items: builtins.list[dict[str, Any]],
        ) -> tuple[builtins.list[dict[str, Any]], None]:
            nonlocal result
            found = next(
                (
                    item
                    for item in items
                    if item.get("id") == schedule_id and item.get("project") == self.project
                ),
                None,
            )
            if found is None:
                return items, None
            if action == "delete":
                result = dict(found)
                return [item for item in items if item.get("id") != schedule_id], None
            found["status"] = "paused" if action == "pause" else "active"
            if action in {"resume", "run"}:
                found["next_run_at"] = (
                    time.time()
                    if action == "run"
                    else time.time() + int(found["interval_minutes"]) * 60
                )
            result = dict(found)
            return items, None

        self.store.mutate("web_schedules", [], change)
        if result is None:
            return {"ok": False, "error": "schedule not found"}
        if action == "run":
            self.tick()
            current = next(
                (item for item in self.list()["schedules"] if item["id"] == schedule_id), result
            )
            return {"ok": True, "schedule": current}
        return {"ok": True, "schedule": result, "deleted": action == "delete"}

    def tick(self) -> None:
        now = time.time()
        snapshot = self.store.read("web_schedules", [])
        if not any(
            item.get("project") == self.project
            and item.get("status") == "active"
            and float(item.get("next_run_at") or 0) <= now
            for item in snapshot
        ):
            return

        def change(
            items: builtins.list[dict[str, Any]],
        ) -> tuple[builtins.list[dict[str, Any]], None]:
            for item in items:
                if (
                    item.get("project") != self.project
                    or item.get("status") != "active"
                    or float(item.get("next_run_at") or 0) > now
                ):
                    continue
                try:
                    job = self.graph_runs.start(
                        str(item.get("path") or ""),
                        params=dict(item.get("params") or {}),
                        approved_gates=list(item.get("approved_gates") or []),
                    )
                    item["last_job_id"] = str(job.get("job_id") or "")
                    item["last_error"] = ""
                except Exception as exc:  # noqa: BLE001 - persisted for the operator
                    item["last_error"] = str(exc)
                item["last_run_at"] = now
                item["next_run_at"] = now + int(item["interval_minutes"]) * 60
            return items, None

        self.store.mutate("web_schedules", [], change)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop() -> None:
            while not self._stop.wait(10):
                self.tick()

        self._thread = threading.Thread(target=loop, name="magent-web-schedules", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
