"""Concurrent execution of consecutive read-only tool calls (G-10)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from magent.activity_events import activity_event

# Tools that only read local state, so several in a row may run at once (G-10).
PARALLEL_READ_ONLY_TOOLS = frozenset(
    {
        "read_file",
        "read_file_range",
        "outline_file",
        "list_dir",
        "search_codebase",
        "diff_files",
        "json_query",
        "magent_docs_search",
        "db_list_tables",
        "db_schema",
    }
)
PARALLEL_READ_DEFAULT = 4


class ParallelReadMixin:
    """Prefetch runs of read-only calls; mixed into the tool loop."""

    config: Any
    logger: Any
    turn_count: int
    _execute_tool_call: Any

    def _max_parallel_read_tools(self) -> int:
        value = getattr(self.config, "max_parallel_read_tools", PARALLEL_READ_DEFAULT)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return PARALLEL_READ_DEFAULT

    def _read_only_segments(self, tool_calls: list[Any]) -> dict[int, list[int]]:
        """Runs of 2+ consecutive read-only calls, keyed by their first index.

        Only tools in PARALLEL_READ_ONLY_TOOLS with well-formed arguments
        qualify, and only when they sit next to each other.
        """
        if self._max_parallel_read_tools() <= 1 or len(tool_calls) < 2:
            return {}
        segments: dict[int, list[int]] = {}
        current: list[int] = []
        for index, tc in enumerate([*tool_calls, None]):
            if tc is not None and _read_only_call(tc) is not None:
                current.append(index)
                continue
            if len(current) > 1:
                segments[current[0]] = current
            current = []
        return segments

    async def _run_read_segment(
        self, tool_calls: list[Any], segment: list[int]
    ) -> dict[int, tuple[dict[str, Any], float]]:
        """Run one segment concurrently (bounded); {call index: (result, start time)}.

        The tool loop calls this only when it reaches the segment's first call,
        so every earlier call (a write, a shell command, an approval that
        stops the turn) has already happened: reads never run ahead of them.
        Any permission prompt a read needs is synchronous, so prompts are
        still asked one at a time.
        """
        limit = self._max_parallel_read_tools()
        semaphore = asyncio.Semaphore(limit)
        results: dict[int, tuple[dict[str, Any], float]] = {}

        async def run(index: int) -> None:
            name, arguments = _read_only_call(tool_calls[index])  # type: ignore[misc]
            async with semaphore:
                started = time.monotonic()
                results[index] = (await self._execute_tool_call(name, arguments), started)

        await asyncio.gather(*(run(index) for index in segment))
        self.logger.log_activity_event(
            activity_event(
                "tool_progress",
                turn=self.turn_count,
                detail={"parallel_read_only": [len(segment)], "limit": limit},
            )
        )
        return results


def _read_only_call(tc: Any) -> tuple[str, dict[str, Any]] | None:
    name = str(getattr(tc.function, "name", "") or "")
    if name not in PARALLEL_READ_ONLY_TOOLS:
        return None
    try:
        arguments = json.loads(tc.function.arguments)
    except (TypeError, json.JSONDecodeError):
        return None
    return (name, arguments) if isinstance(arguments, dict) else None
