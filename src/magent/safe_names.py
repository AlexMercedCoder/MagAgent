"""One place to turn a caller-supplied identifier into a path component.

Memory node ids, plugin names and state keys, database and user names, and
artifact paths were each sanitised differently — or not at all. An id that
reaches the filesystem is a path traversal waiting to happen, so every such
conversion should come through here.

Two levels are offered:

* `safe_component(value)` — strict. Rejects anything that is not already a
  plain, safe name. Use when the caller controls the value and a bad one is a
  bug worth surfacing (plugin names, database names).
* `slugify_component(value)` — lossy but total. Percent-encodes whatever it is
  given so *any* input produces a usable, contained component. Use when the
  value comes from a model or a remote peer and rejecting it would break a
  legitimate workflow (memory node ids, artifact names).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, unquote

__all__ = [
    "InvalidNameError",
    "strip_component",
    "contained_path",
    "is_safe_component",
    "safe_component",
    "slugify_component",
    "unslugify_component",
]

# A component that is safe on every platform we support: no separators, no
# traversal, no device names, no leading dash.
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Reserved on Windows regardless of extension.
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class InvalidNameError(ValueError):
    """A supplied identifier cannot be used as a path component."""


def is_safe_component(value: str) -> bool:
    if not isinstance(value, str) or not _SAFE_COMPONENT.match(value):
        return False
    return not (value in {".", ".."} or value.split(".")[0].lower() in _RESERVED)


def safe_component(value: str, *, label: str = "name") -> str:
    """Return `value` when it is already a safe component, else raise."""
    if not is_safe_component(value):
        raise InvalidNameError(
            f"{label} must be 1-128 characters of letters, digits, dot, dash or "
            f"underscore and may not traverse directories: {value!r}"
        )
    return value


def slugify_component(value: str, *, fallback: str = "unnamed") -> str:
    """Return a safe component for any input, without rejecting it.

    Percent-encoding keeps ordinary names untouched (so existing on-disk data
    keeps working) while making separators and traversal impossible to express.
    """
    text = str(value or "").strip()
    if not text:
        return fallback

    encoded = quote(text, safe="._-")
    encoded = encoded.replace("%", "~")  # '%' is awkward in shells and globs

    if encoded in {".", "..", "~2E", "~2E~2E"}:
        return fallback
    if encoded.split(".")[0].lower() in _RESERVED:
        encoded = f"_{encoded}"
    if not encoded[:1].isalnum():
        encoded = f"_{encoded}"
    return encoded[:128] or fallback


def strip_component(value: str, *, fallback: str = "default") -> str:
    """Drop unsafe characters instead of encoding them.

    Lossier than `slugify_component` (two different inputs can collide) but it
    leaves ordinary names byte-identical, which matters where the result is
    already an on-disk filename people have data under.
    """
    text = "".join(
        char for char in str(value or "") if char.isalnum() or char in "-_."
    ).strip("._-")
    if not text or text in {".", ".."}:
        return fallback
    if text.split(".")[0].lower() in _RESERVED:
        text = f"_{text}"
    return text[:128] or fallback


def unslugify_component(component: str) -> str:
    """Best-effort inverse of `slugify_component`."""
    try:
        return unquote(str(component).replace("~", "%"))
    except Exception:
        return str(component)


def contained_path(root: Path | str, *parts: str, strict: bool = True) -> Path:
    """Join `parts` under `root`, refusing anything that escapes it.

    Resolves the root as well as the candidate: comparing a resolved candidate
    against an unresolved root gives both false rejections (a root that is
    itself a symlink) and potential bypasses.
    """
    base = Path(root).resolve(strict=False)
    components = [safe_component(part) if strict else slugify_component(part) for part in parts]
    candidate = base.joinpath(*components).resolve(strict=False)
    if candidate != base and base not in candidate.parents:
        raise InvalidNameError(f"path escapes {base}: {'/'.join(parts)}")
    return candidate
