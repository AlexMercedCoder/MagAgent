"""Reusable live provider tool-use smoke checks."""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any

from magent.agent import AgentSession
from magent.ask_audit import audit_one_shot_task
from magent.cli.command_context import build_extraction_provider, build_provider
from magent.model_health import record_model_health

SMOKE_PROMPT = "Use write_file to create smoke.txt containing exactly OK. Do not run shell commands."


def run_provider_tool_smoke(
    username: str,
    config: Any,
    store: Any,
    provider_id: str,
    *,
    model: str | None = None,
    project: str | Path | None = None,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Run a tiny live provider smoke test and record a model health observation."""
    root_ctx = (
        tempfile.TemporaryDirectory(prefix="magent-provider-smoke-")
        if project is None
        else None
    )
    root = Path(project or root_ctx.name).resolve()  # type: ignore[union-attr]
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    provider = build_provider(config, provider_id, model)
    session = AgentSession(
        username=username,
        config=config,
        provider=provider,
        extraction_provider=build_extraction_provider(config),
        cwd=str(root),
        interactive_permissions=False,
        permission_mode_override="yolo",
    )

    async def _run() -> str:
        try:
            return await session.chat(SMOKE_PROMPT)
        finally:
            await session.end_session()

    error = ""
    response = ""
    try:
        response = asyncio.run(asyncio.wait_for(_run(), timeout=timeout_seconds))
    except TimeoutError:
        error = f"Provider smoke timed out after {timeout_seconds}s"
    except Exception as e:
        error = str(e)
    latency_ms = int((time.perf_counter() - started) * 1000)
    smoke_path = root / "smoke.txt"
    content = smoke_path.read_text(encoding="utf-8").strip() if smoke_path.exists() else ""
    audit = audit_one_shot_task(SMOKE_PROMPT, root, session.scratchpad)
    ok = content == "OK" and audit["ok"] and not error
    result = {
        "ok": ok,
        "provider": provider_id,
        "model": provider.model,
        "project": str(root),
        "artifact": str(smoke_path),
        "artifact_ok": content == "OK",
        "latency_ms": latency_ms,
        "audit": audit,
        "response_preview": response[:500],
        "error": error[:500],
    }
    record_model_health(
        store,
        provider_id,
        provider.model,
        task_type="tool-use",
        ok=ok,
        latency_ms=latency_ms,
        error=error or response[:500],
        metadata={"artifact_ok": content == "OK", "audit_ok": audit["ok"]},
    )
    if root_ctx is not None:
        root_ctx.cleanup()
    return result
