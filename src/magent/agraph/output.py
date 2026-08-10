"""Task-local output collection for graph node agents."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_collector: ContextVar[dict[str, Any] | None] = ContextVar("magent_graph_outputs", default=None)


def begin_output_collection() -> tuple[dict[str, Any], Token[dict[str, Any] | None]]:
    values: dict[str, Any] = {}
    return values, _collector.set(values)


def end_output_collection(token: Token[dict[str, Any] | None]) -> None:
    _collector.reset(token)


def emit_output(name: str, value: Any) -> dict[str, Any]:
    values = _collector.get()
    if values is None:
        return {"ok": False, "error": "graph_emit_output is only available during graph node execution"}
    normalized = str(name).strip()
    if not normalized:
        return {"ok": False, "error": "output name is required"}
    values[normalized] = value
    return {"ok": True, "name": normalized}
