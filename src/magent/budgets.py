"""Spend guardrails.

Token and cost telemetry was already logged per turn, but nothing ever acted on
it: a runaway loop or an expensive model could spend without limit and the only
way to find out was to read the logs afterwards.

Two limits, both optional:

    [budgets]
    session_usd = 5.0      # hard stop for one session
    daily_usd  = 25.0      # hard stop for a rolling 24 hours
    warn_at    = 0.8       # warn once at this fraction of a limit

`check()` is called before each model round. Over a limit it returns a
`BudgetExceeded` verdict and the caller stops the turn; the agent never
silently keeps spending.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = ["BudgetStatus", "SpendTracker", "budget_config", "daily_spend"]


@dataclass(frozen=True)
class BudgetStatus:
    """Outcome of a budget check."""

    ok: bool
    reason: str = ""
    warning: str = ""
    session_usd: float = 0.0
    daily_usd: float = 0.0
    session_limit: float = 0.0
    daily_limit: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "warning": self.warning,
            "session_usd": round(self.session_usd, 6),
            "daily_usd": round(self.daily_usd, 6),
            "session_limit": self.session_limit,
            "daily_limit": self.daily_limit,
        }


def budget_config(config: Any) -> dict[str, float]:
    """Read the `[budgets]` section, tolerating its absence."""
    getter = getattr(config, "get", None)
    raw = getter("budgets", default={}) if callable(getter) else {}
    if not isinstance(raw, dict):
        raw = {}

    def number(key: str, default: float) -> float:
        try:
            return max(0.0, float(raw.get(key, default) or 0.0))
        except (TypeError, ValueError):
            return default

    return {
        "session_usd": number("session_usd", 0.0),
        "daily_usd": number("daily_usd", 0.0),
        "warn_at": min(1.0, number("warn_at", 0.8)) or 0.8,
    }


def daily_spend(hours: int = 24) -> float:
    """USD logged across all sessions in the last `hours`.

    Reads the same token_usage events `usage_stats` aggregates.
    """
    import json

    from magent.config import LOGS_DIR

    if not LOGS_DIR.exists():
        return 0.0

    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    total = 0.0

    for path in LOGS_DIR.glob("*.jsonl"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for line in text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "token_usage":
                continue
            stamp = event.get("timestamp") or event.get("time") or ""
            try:
                if stamp and datetime.fromisoformat(str(stamp)) < cutoff:
                    continue
            except ValueError:
                pass
            total += float(event.get("cost_usd") or 0.0)

    return total


class SpendTracker:
    """Accumulates session spend and enforces the configured limits."""

    def __init__(self, config: Any):
        self.limits = budget_config(config)
        self.session_usd = 0.0
        self._warned: set[str] = set()
        self._daily_cache: tuple[float, float] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.limits["session_usd"] or self.limits["daily_usd"])

    def record(self, cost_usd: float) -> None:
        """Add the cost of one model call."""
        try:
            self.session_usd += max(0.0, float(cost_usd or 0.0))
        except (TypeError, ValueError):
            return
        self._daily_cache = None

    def _daily(self) -> float:
        import time as _time

        if self._daily_cache and _time.monotonic() - self._daily_cache[0] < 60:
            return self._daily_cache[1]
        spent = daily_spend() + self.session_usd
        self._daily_cache = (_time.monotonic(), spent)
        return spent

    def check(self) -> BudgetStatus:
        """Whether another model call is allowed."""
        session_limit = self.limits["session_usd"]
        daily_limit = self.limits["daily_usd"]
        if not self.enabled:
            return BudgetStatus(ok=True, session_usd=self.session_usd)

        daily = self._daily() if daily_limit else 0.0

        if session_limit and self.session_usd >= session_limit:
            return BudgetStatus(
                ok=False,
                reason=(
                    f"Session budget reached: ${self.session_usd:.4f} of ${session_limit:.2f}. "
                    "Raise budgets.session_usd or start a new session."
                ),
                session_usd=self.session_usd,
                daily_usd=daily,
                session_limit=session_limit,
                daily_limit=daily_limit,
            )

        if daily_limit and daily >= daily_limit:
            return BudgetStatus(
                ok=False,
                reason=(
                    f"Daily budget reached: ${daily:.4f} of ${daily_limit:.2f} in the last 24h. "
                    "Raise budgets.daily_usd to continue."
                ),
                session_usd=self.session_usd,
                daily_usd=daily,
                session_limit=session_limit,
                daily_limit=daily_limit,
            )

        warning = ""
        threshold = self.limits["warn_at"]
        if session_limit and self.session_usd >= session_limit * threshold and "session" not in self._warned:
            self._warned.add("session")
            warning = f"Session spend ${self.session_usd:.4f} is over {threshold:.0%} of ${session_limit:.2f}."
        elif daily_limit and daily >= daily_limit * threshold and "daily" not in self._warned:
            self._warned.add("daily")
            warning = f"Daily spend ${daily:.4f} is over {threshold:.0%} of ${daily_limit:.2f}."

        return BudgetStatus(
            ok=True,
            warning=warning,
            session_usd=self.session_usd,
            daily_usd=daily,
            session_limit=session_limit,
            daily_limit=daily_limit,
        )
