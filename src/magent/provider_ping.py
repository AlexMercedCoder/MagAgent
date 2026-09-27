"""Minimal provider connectivity check (G-9).

One chat completion, a one-line prompt and at most 16 output tokens: enough to
prove the credential, endpoint and model name work, at negligible cost. It is
*not* a qualification run (no tools, streaming or retries are exercised), so a
passing ping refreshes a provider's evidence date but does not raise its tier.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent.secret_scrub import scrub_secrets

PING_SCHEMA = "magent.provider-ping.v1"
PROMPT = "Reply with the single word OK."
MAX_TOKENS_LIMIT = 16


def ping_provider(
    config: Any, provider_id: str, model: str = "", max_tokens: int = 16
) -> dict[str, Any]:
    from magent.cli.command_context import build_provider

    max_tokens = max(1, min(int(max_tokens), MAX_TOKENS_LIMIT))
    record: dict[str, Any] = {
        "schema": PING_SCHEMA,
        "provider": provider_id,
        "model": model,
        "checked_at": datetime.now(UTC).isoformat(),
        "max_tokens": max_tokens,
        "prompt": PROMPT,
    }
    try:
        provider = build_provider(config, provider_id, model or None)
    except Exception as error:
        return {**record, "ok": False, "error": scrub_secrets(str(error))[:500]}
    record["provider"], record["model"] = provider.provider_id, provider.model
    started = time.perf_counter()
    try:
        import litellm

        litellm.suppress_debug_info = True
        from magent.providers import flush_provider_logging

        params = provider.completion_params(0.0, max_tokens)

        async def call() -> Any:
            try:
                return await litellm.acompletion(
                    messages=[{"role": "user", "content": PROMPT}],
                    **params,
                    **provider.request_kwargs(),
                )
            finally:
                # Drain LiteLLM's logging worker inside this loop, or it warns
                # about a changed event loop on the next call.
                await flush_provider_logging()

        response = asyncio.run(call())
    except Exception as error:
        return {
            **record,
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": scrub_secrets(str(error))[:500],
        }
    choice = response.choices[0]
    usage = getattr(response, "usage", None)
    return {
        **record,
        "ok": True,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "finish_reason": str(getattr(choice, "finish_reason", "") or ""),
        "reply": str(getattr(choice.message, "content", "") or "")[:40],
        "usage": {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        },
    }


def append_record(path: str | Path, record: dict[str, Any]) -> None:
    target = Path(path)
    existing: dict[str, Any] = {"schema": "magent.provider-connectivity.v1", "checks": []}
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
    existing.setdefault("checks", []).append(record)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
