"""Cross-session provider cooldown state for rate limits."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from magent.config import CONFIG_DIR

COOLDOWN_DIR = CONFIG_DIR / "rate_limits"


def _path(provider_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in provider_id)
    return COOLDOWN_DIR / f"{safe}.json"


def record_provider_cooldown(provider_id: str, seconds: float, reason: str = "rate limited") -> dict[str, Any]:
    COOLDOWN_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    reset_at = now + max(1.0, float(seconds))
    data = {"provider": provider_id, "recorded_at": now, "reset_at": reset_at, "reason": reason}
    _path(provider_id).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, **data, "remaining_seconds": reset_at - now}


def provider_cooldown_remaining(provider_id: str) -> float | None:
    path = _path(provider_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        remaining = float(data.get("reset_at", 0)) - time.time()
    except Exception:
        return None
    if remaining > 0:
        return remaining
    try:
        path.unlink()
    except OSError:
        pass
    return None


def clear_provider_cooldown(provider_id: str) -> dict[str, Any]:
    existed = _path(provider_id).exists()
    try:
        _path(provider_id).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True, "provider": provider_id, "cleared": existed}


def list_provider_cooldowns() -> dict[str, Any]:
    rows = []
    if COOLDOWN_DIR.exists():
        for path in sorted(COOLDOWN_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            remaining = provider_cooldown_remaining(str(data.get("provider") or path.stem))
            if remaining is not None:
                rows.append({**data, "remaining_seconds": remaining})
    return {"ok": True, "cooldowns": rows}


def cooldown_from_exception(provider_id: str, exc: Exception) -> dict[str, Any] | None:
    text = str(exc).lower()
    if "rate limit" not in text and "429" not in text:
        return None
    return record_provider_cooldown(provider_id, 300, reason=str(exc)[:240])
