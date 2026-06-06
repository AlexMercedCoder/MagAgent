"""Workbench storage statistics, pruning, and compaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HIGH_VOLUME_STORES = {
    "command_history": 500,
    "events": 500,
    "sandbox_runs": 100,
    "eval_runs": 100,
    "checkpoints": 250,
}


def workbench_stats(store: Any) -> dict[str, Any]:
    """Return file and record counts for one user's workbench."""
    root = Path(store.root)
    files = []
    total_bytes = 0
    for path in sorted(root.glob("*.json")):
        size = path.stat().st_size
        total_bytes += size
        data = _read_json(path)
        files.append(
            {
                "store": path.stem,
                "path": str(path),
                "bytes": size,
                "records": len(data) if isinstance(data, list) else (len(data) if isinstance(data, dict) else 0),
                "high_volume": path.stem in HIGH_VOLUME_STORES,
            }
        )
    checkpoint_bytes = _dir_size(root / "checkpoints")
    total_bytes += checkpoint_bytes
    return {
        "ok": True,
        "root": str(root),
        "stores": files,
        "total_bytes": total_bytes,
        "checkpoint_bytes": checkpoint_bytes,
        "recommendations": _recommendations(files, checkpoint_bytes),
    }


def prune_workbench(
    store: Any,
    *,
    older_than_days: int = 30,
    keep: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prune old high-volume workbench records while keeping recent entries."""
    cutoff = datetime.now(UTC) - timedelta(days=max(1, older_than_days))
    keep_counts = dict(HIGH_VOLUME_STORES)
    if keep is not None:
        keep_counts = {name: max(0, keep) for name in keep_counts}
    changes = []
    for name, keep_count in keep_counts.items():
        path = Path(store.root) / f"{name}.json"
        data = _read_json(path)
        if not isinstance(data, list):
            continue
        original = len(data)
        recent = [item for item in data if _record_time(item) and _record_time(item) >= cutoff]
        kept_by_count = data[-keep_count:] if keep_count else []
        merged = _dedupe_records([*recent, *kept_by_count])
        removed = original - len(merged)
        if removed > 0 and not dry_run:
            store.write(name, merged)
        changes.append({"store": name, "before": original, "after": len(merged), "removed": removed})
    return {"ok": True, "dry_run": dry_run, "older_than_days": older_than_days, "changes": changes}


def compact_workbench(store: Any) -> dict[str, Any]:
    """Rewrite JSON stores with stable indentation and report bytes reclaimed."""
    root = Path(store.root)
    results = []
    before_total = 0
    after_total = 0
    for path in sorted(root.glob("*.json")):
        before = path.stat().st_size
        before_total += before
        data = _read_json(path)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        after = path.stat().st_size
        after_total += after
        results.append({"store": path.stem, "before_bytes": before, "after_bytes": after})
    return {
        "ok": True,
        "before_bytes": before_total,
        "after_bytes": after_total,
        "bytes_reclaimed": max(0, before_total - after_total),
        "stores": results,
    }


def _read_json(path: Path) -> Any:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _record_time(item: dict[str, Any]) -> datetime | None:
    raw = item.get("updated_at") or item.get("created_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _dedupe_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = item.get("id") or json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    result.sort(key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""))
    return result


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _recommendations(files: list[dict[str, Any]], checkpoint_bytes: int) -> list[str]:
    recommendations = []
    for item in files:
        if item["store"] in HIGH_VOLUME_STORES and item["records"] > HIGH_VOLUME_STORES[item["store"]]:
            recommendations.append(f"Prune `{item['store']}`; it has {item['records']} records.")
        if item["bytes"] > 2_000_000:
            recommendations.append(f"Compact `{item['store']}`; JSON file is over 2 MB.")
    if checkpoint_bytes > 25_000_000:
        recommendations.append("Review checkpoints; backup content is over 25 MB.")
    return recommendations
