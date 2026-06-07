"""High-level readiness checks for daily MagAgent use."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magent.config_ux import doctor_actions, provider_matrix
from magent.docs import docs_doctor
from magent.model_health import model_health_report, recommend_model_from_health
from magent.provider_smoke import run_provider_tool_smoke
from magent.workbench import project_doctor


def readiness_report(
    username: str,
    config: Any,
    store: Any,
    *,
    project: str | Path = ".",
    smoke: bool = False,
    provider_id: str | None = None,
    model: str | None = None,
    smoke_timeout: int = 90,
) -> dict[str, Any]:
    """Return one concise readiness report for setup, docs, project, and models."""
    provider_id = provider_id or config.default_provider
    root = Path(project).resolve()
    providers = provider_matrix()["providers"]
    provider_row = next((item for item in providers if item["id"] == provider_id), None)
    provider_ready = bool(provider_row and provider_row.get("ready"))
    docs = docs_doctor()
    project_result = project_doctor(root, store)
    doctor = doctor_actions(username)
    health = model_health_report(store, limit=10)
    recommendation = recommend_model_from_health(store, provider=provider_id, task_type="tool-use")
    smoke_result = None
    if smoke:
        smoke_result = run_provider_tool_smoke(
            username,
            config,
            store,
            provider_id,
            model=model,
            project=root / ".magent" / "smoke",
            timeout_seconds=smoke_timeout,
        )
        recommendation = recommend_model_from_health(store, provider=provider_id, task_type="tool-use")
    checks = [
        {"key": "provider", "ok": provider_ready, "detail": provider_row or {}},
        {"key": "docs", "ok": docs["ok"], "detail": docs},
        {"key": "project", "ok": project_result["ok"], "detail": project_result},
        {"key": "doctor", "ok": doctor["ok"], "detail": doctor},
    ]
    if smoke_result is not None:
        checks.append({"key": "provider_tool_smoke", "ok": smoke_result["ok"], "detail": smoke_result})
    return {
        "ok": all(item["ok"] for item in checks),
        "project": str(root),
        "provider": provider_id,
        "model": model or config.provider_config(provider_id).get("default_model") or config.default_model,
        "checks": checks,
        "smoke": smoke_result,
        "model_health": health,
        "recommendation": recommendation,
        "next": _next_actions(checks, recommendation),
    }


def _next_actions(checks: list[dict[str, Any]], recommendation: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    failed = {item["key"] for item in checks if not item["ok"]}
    if "provider" in failed:
        actions.append("magent provider wizard")
    if "docs" in failed:
        actions.append("magent docs doctor")
    if "project" in failed:
        actions.append("magent project wizard")
    if not recommendation.get("ok"):
        actions.append("magent provider tool-smoke <provider> --model <cheap-model>")
    return actions or ["magent ask \"Summarize this project and suggest the next useful task.\""]
