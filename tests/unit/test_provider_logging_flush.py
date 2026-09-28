"""flush_provider_logging must not hang when LiteLLM's logging queue never drains."""

from __future__ import annotations

import asyncio
import time

import pytest

import magent.providers as providers


class _StuckWorker:
    def __init__(self) -> None:
        self.stopped = False

    async def flush(self) -> None:
        await asyncio.Event().wait()  # like queue.join() with nobody consuming

    async def stop(self) -> None:
        self.stopped = True


def test_flush_is_bounded_when_the_logging_queue_never_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("litellm")
    import litellm.litellm_core_utils.logging_worker as logging_worker

    worker = _StuckWorker()
    monkeypatch.setattr(logging_worker, "GLOBAL_LOGGING_WORKER", worker)
    monkeypatch.setattr(providers, "LOGGING_FLUSH_TIMEOUT_SECONDS", 0.2, raising=False)

    started = time.monotonic()
    asyncio.run(asyncio.wait_for(providers.flush_provider_logging(), 10))

    assert time.monotonic() - started < 5
