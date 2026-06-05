"""Small token-budget helpers.

These intentionally use a cheap character heuristic so MagAgent can budget
context without provider-specific tokenizers or extra network/model calls.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Estimate token count using the common 4 chars ~= 1 token rule."""
    return max(1, (len(text) + 3) // 4) if text else 0


def truncate_to_tokens(text: str, max_tokens: int, marker: str = "[...truncated...]") -> str:
    """Truncate text to an approximate token budget."""
    if max_tokens <= 0:
        return ""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    marker_text = f"\n\n{marker}"
    return text[: max(0, max_chars - len(marker_text))].rstrip() + marker_text
