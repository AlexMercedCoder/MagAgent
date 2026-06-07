"""Durable provider/model health observations."""

from __future__ import annotations

from typing import Any

from magent.workbench_store import now_iso

HEALTH_STORE = "model_health"


def record_model_health(
    store: Any,
    provider: str,
    model: str,
    *,
    task_type: str,
    ok: bool,
    latency_ms: int | None = None,
    error: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a bounded model health observation to the workbench store."""
    records = list(store.read(HEALTH_STORE, []))
    item = {
        "id": f"health_{len(records) + 1:04d}",
        "created_at": now_iso(),
        "provider": provider,
        "model": model,
        "task_type": task_type,
        "ok": ok,
        "latency_ms": latency_ms,
        "error": error[:500],
        "metadata": metadata or {},
    }
    records.append(item)
    store.write(HEALTH_STORE, records[-200:])
    return item


def model_health_report(store: Any, limit: int = 50) -> dict[str, Any]:
    """Return recent observations plus aggregate pass counts by provider/model/task."""
    records = list(store.read(HEALTH_STORE, []))
    aggregates: dict[str, dict[str, Any]] = {}
    for record in records:
        key = "|".join(
            [
                str(record.get("provider", "")),
                str(record.get("model", "")),
                str(record.get("task_type", "")),
            ]
        )
        entry = aggregates.setdefault(
            key,
            {
                "provider": record.get("provider", ""),
                "model": record.get("model", ""),
                "task_type": record.get("task_type", ""),
                "runs": 0,
                "passes": 0,
                "failures": 0,
                "last_ok": None,
                "last_error": "",
                "last_tested_at": "",
            },
        )
        entry["runs"] += 1
        if record.get("ok"):
            entry["passes"] += 1
        else:
            entry["failures"] += 1
            entry["last_error"] = record.get("error", "")
        entry["last_ok"] = bool(record.get("ok"))
        entry["last_tested_at"] = record.get("created_at", "")
    return {
        "ok": True,
        "recent": list(reversed(records))[:limit],
        "models": sorted(
            aggregates.values(),
            key=lambda item: (item["last_tested_at"], item["provider"], item["model"]),
            reverse=True,
        ),
    }


def recommend_model_from_health(
    store: Any,
    *,
    provider: str | None = None,
    task_type: str = "tool-use",
) -> dict[str, Any]:
    """Recommend the best recently successful model for a task type."""
    report = model_health_report(store)
    candidates = [
        item
        for item in report["models"]
        if item["task_type"] == task_type
        and item["passes"] > 0
        and (provider is None or item["provider"] == provider)
    ]
    candidates.sort(key=lambda item: (item["passes"] - item["failures"], item["last_tested_at"]), reverse=True)
    if not candidates:
        return {"ok": False, "error": "No successful model health observations found."}
    return {"ok": True, "recommendation": candidates[0], "candidates": candidates[:5]}
