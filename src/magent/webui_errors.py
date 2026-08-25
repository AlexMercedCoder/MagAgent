"""Turn a runtime exception into something a person can act on.

A failed turn used to put `str(exc)` straight into the transcript as an
assistant message, so a missing API key, an unreachable provider, and a
permission denial all arrived as a Python repr in a chat bubble.

Each rule here names the state and says what to do about it. The original text
is preserved separately so nothing is lost for debugging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FriendlyError:
    """A named failure with a recovery step."""

    kind: str
    """Stable machine-readable identifier, e.g. ``missing_credential``."""

    message: str
    """One sentence naming what happened."""

    action: str
    """The command or step that fixes it. May be empty."""

    detail: str
    """The original exception text, kept for diagnosis."""

    def as_event(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "error": self.message,
            "action": self.action,
            "detail": self.detail,
        }

    def as_message(self) -> str:
        return f"{self.message} {self.action}".strip()


# Ordered: the first pattern that matches wins, so put the specific ones first.
_RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        r"api[_ ]?key|no such key|missing credential|unauthor|401|invalid.*token",
        "missing_credential",
        "That provider has no usable credential.",
        "Set the provider's API key in your environment, or run `magent configure` to pick a provider that has one.",
    ),
    (
        r"rate.?limit|429|too many requests|quota",
        "rate_limited",
        "The provider is rate limiting this key.",
        "Wait a moment and send again, or switch providers with `magent configure`.",
    ),
    (
        r"timed? ?out|timeout|deadline exceeded",
        "timeout",
        "The provider did not answer in time.",
        "Send again. If it keeps happening, check `magent doctor` for provider health.",
    ),
    (
        r"connection|unreachable|network|dns|getaddrinfo|refused|ssl|certificate",
        "provider_unreachable",
        "MagAgent could not reach the provider.",
        "Check your network, then run `magent doctor`.",
    ),
    (
        r"permission|not permitted|denied|forbidden|policy",
        "permission_denied",
        "That step was blocked by the permission policy.",
        "Review the mode in Settings, or run `magent mode` to change the default.",
    ),
    (
        r"budget|spend limit|max tokens exceeded|context length|too long|maximum context",
        "budget_exhausted",
        "The turn exceeded a size or budget limit.",
        "Start a new conversation, or narrow the request.",
    ),
    (
        r"model|not found.*model|unknown model|unsupported",
        "model_unavailable",
        "That model is not available on the configured provider.",
        "Pick another with `magent model` or `magent configure`.",
    ),
    (
        r"cancel",
        "cancelled",
        "The turn was cancelled.",
        "",
    ),
    (
        r"profile|agent not found",
        "profile_problem",
        "The selected agent profile could not be used.",
        "Check it with `magent agent explain`, or pick another in Profiles.",
    ),
)


def describe(exc: BaseException) -> FriendlyError:
    """Classify `exc` into a named, actionable failure."""
    detail = str(exc).strip() or exc.__class__.__name__
    haystack = f"{exc.__class__.__name__} {detail}".lower()

    for pattern, kind, message, action in _RULES:
        if re.search(pattern, haystack):
            return FriendlyError(kind=kind, message=message, action=action, detail=detail)

    return FriendlyError(
        kind="unexpected",
        message="The turn failed.",
        action="The details are below; `magent doctor` checks the usual causes.",
        detail=detail,
    )
