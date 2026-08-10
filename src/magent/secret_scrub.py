"""Scrub credential-shaped text before it leaves the process.

LiteLLM exception strings routinely embed the request URL, headers and
sometimes the key itself. The gateway forwarded those verbatim to Slack,
Discord and Telegram, so one upstream 401 could publish an API key into a
channel.
"""

from __future__ import annotations

import re
import uuid

__all__ = ["correlation_id", "safe_error_message", "scrub_secrets"]

# Provider key shapes, longest/most specific first.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "sk-***"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "xox***"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "gh***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "AIza***"),
    (re.compile(r"\bya29\.[0-9A-Za-z_-]+"), "ya29.***"),
    (re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "jwt-***"),
    # key=value / "key": "value" forms in URLs, headers and json blobs
    (
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|authorization|bearer|"
            r"secret|password|passwd|private[_-]?key|client[_-]?secret|session[_-]?token)"
            r"(\"?\s*[:=]\s*\"?|\s+)([A-Za-z0-9._~+/=-]{8,})"
        ),
        r"\1\2***",
    ),
]


def scrub_secrets(text: str) -> str:
    """Replace anything that looks like a credential with a marker."""
    if not text:
        return text
    scrubbed = str(text)
    for pattern, replacement in _PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def correlation_id() -> str:
    """Short id so a generic chat message can be tied to the local log line."""
    return uuid.uuid4().hex[:8]


def safe_error_message(error: BaseException, *, reference: str | None = None) -> str:
    """A message safe to send to a chat platform.

    The detail stays in the local console/log; the remote user gets the error
    type and a reference to quote.
    """
    marker = reference or correlation_id()
    return f"{type(error).__name__} (ref {marker}) — see the MagAgent gateway log for details"
