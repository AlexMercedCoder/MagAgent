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

    async def _prefetch_read_only_calls(
        self, tool_calls: list[Any]
    ) -> dict[int, tuple[dict[str, Any], float]]:
        """Run each run of 2+ consecutive read-only calls concurrently.

        Only tools in PARALLEL_READ_ONLY_TOOLS qualify, only when they sit next
        to each other (a read after a write must see the write), and at most
        ``agent.max_parallel_read_tools`` at a time. Any permission prompt a
        read needs is synchronous, so prompts are still asked one at a time.
        Returns {call index: (result, start time)}.
        """
        limit = self._max_parallel_read_tools()
        if limit <= 1 or len(tool_calls) < 2:
            return {}
        parsed: list[tuple[str, dict[str, Any]] | None] = []
        for tc in tool_calls:
            name = str(getattr(tc.function, "name", "") or "")
            try:
                arguments = json.loads(tc.function.arguments)
            except (TypeError, json.JSONDecodeError):
                arguments = None
            parsed.append(
                (name, arguments)
                if name in PARALLEL_READ_ONLY_TOOLS and isinstance(arguments, dict)
                else None
            )
        segments: list[list[int]] = []
        current: list[int] = []
        for index, item in enumerate(parsed):
            if item is None:
                if len(current) > 1:
                    segments.append(current)
                current = []
            else:
                current.append(index)
        if len(current) > 1:
            segments.append(current)
        if not segments:
            return {}
        semaphore = asyncio.Semaphore(limit)
        results: dict[int, tuple[dict[str, Any], float]] = {}

        async def run(index: int) -> None:
            name, arguments = parsed[index]  # type: ignore[misc]
            async with semaphore:
                started = time.monotonic()
                results[index] = (await self._execute_tool_call(name, arguments), started)

        for segment in segments:
            await asyncio.gather(*(run(index) for index in segment))
        self.logger.log_activity_event(
            activity_event(
                "tool_progress",
                turn=self.turn_count,
                detail={
                    "parallel_read_only": [len(segment) for segment in segments],
                    "limit": limit,
                },
            )
        )
        return results
