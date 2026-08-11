"""Deterministic labeled evaluations for memory retrieval quality."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from magent.tokens import estimate_tokens
from magent.workbench_store import now_iso


def run_memory_eval(memory_manager: Any, suite_path: str | Path) -> dict[str, Any]:
    path = Path(suite_path).resolve()
    suite = json.loads(path.read_text(encoding="utf-8"))
    cases = [_run_case(memory_manager, case) for case in suite.get("cases", [])]
    count = len(cases)
    metrics = {
        "precision": _average(cases, "precision"),
        "recall": _average(cases, "recall"),
        "mean_reciprocal_rank": _average(cases, "reciprocal_rank"),
        "stale_hit_rate": _average(cases, "stale_hit_rate"),
        "contradiction_hit_rate": _average(cases, "contradiction_hit_rate"),
        "project_scope_accuracy": _average(cases, "project_scope_accuracy"),
        "explanation_coverage": _average(cases, "explanation_coverage"),
        "provenance_coverage": _average(cases, "provenance_coverage"),
        "backlink_coverage": _average(cases, "backlink_coverage"),
        "average_context_tokens": round(
            sum(int(case["context_tokens"]) for case in cases) / max(count, 1), 2
        ),
        "budget_pass_rate": round(
            sum(bool(case["budget_ok"]) for case in cases) / max(count, 1), 4
        ),
    }
    thresholds = _thresholds(suite.get("thresholds"))
    gates = _evaluate_thresholds(metrics, thresholds)
    return {
        "schema": "magent.memory-eval.v2",
        "ok": bool(cases) and all(case["ok"] for case in cases) and all(gates.values()),
        "suite": suite.get("name", path.stem),
        "path": str(path),
        "cases": cases,
        "metrics": metrics,
        "thresholds": thresholds,
        "gates": gates,
        "ran_at": now_iso(),
    }


def _run_case(memory_manager: Any, case: dict[str, Any]) -> dict[str, Any]:
    query = str(case.get("query") or "")
    limit = max(1, int(case.get("limit") or 5))
    expected = {str(item) for item in case.get("expected_ids", [])}
    stale_ids = {str(item) for item in case.get("forbidden_ids", [])}
    stale_ids.update(str(item) for item in case.get("stale_ids", []))
    contradiction_ids = {str(item) for item in case.get("contradiction_ids", [])}
    results = memory_manager.search(query, max_results=limit, mode="hybrid")
    ids = [str(item.get("id") or "") for item in results if item.get("id")]
    relevant = len(expected.intersection(ids))
    stale = len(stale_ids.intersection(ids))
    contradictions = len(contradiction_ids.intersection(ids))
    context = memory_manager.recall(query)
    context_tokens = estimate_tokens(context)
    budget = max(1, int(case.get("max_context_tokens") or memory_manager.budget_tokens))
    explained = sum(bool(item.get("reason") or item.get("reasons")) for item in results)
    provenance = sum(bool(_provenance(item)) for item in results)
    backlinks = sum(bool(item.get("backlinks")) for item in results)
    expected_project = str(case.get("expected_project") or "").strip()
    scoped = [item for item in results if _project(item)]
    project_matches = sum(_project(item) == expected_project for item in scoped)
    project_scope_accuracy = (
        project_matches / max(len(scoped), 1) if expected_project else 1.0
    )
    first_relevant = next((position for position, node_id in enumerate(ids, 1) if node_id in expected), 0)
    required_backlinks = bool(case.get("require_backlinks", False))
    required_provenance = bool(case.get("require_provenance", False))
    requirements_ok = (
        not stale
        and not contradictions
        and (not expected or relevant > 0)
        and (not expected_project or project_scope_accuracy == 1.0)
        and (not required_backlinks or backlinks == len(results))
        and (not required_provenance or provenance == len(results))
    )
    return {
        "id": str(case.get("id") or query[:60]),
        "query": query,
        "result_ids": ids,
        "precision": round(relevant / max(len(ids), 1), 4),
        "recall": round(relevant / max(len(expected), 1), 4),
        "reciprocal_rank": round(1 / first_relevant, 4) if first_relevant else 0.0,
        "stale_hit_rate": round(stale / max(len(ids), 1), 4),
        "contradiction_hit_rate": round(contradictions / max(len(ids), 1), 4),
        "project_scope_accuracy": round(project_scope_accuracy, 4),
        "explanation_coverage": round(explained / max(len(results), 1), 4),
        "provenance_coverage": round(provenance / max(len(results), 1), 4),
        "backlink_coverage": round(backlinks / max(len(results), 1), 4),
        "context_tokens": context_tokens,
        "max_context_tokens": budget,
        "budget_ok": context_tokens <= budget,
        "requirements_ok": requirements_ok,
        "ok": context_tokens <= budget and requirements_ok,
    }


def _average(cases: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(case[key]) for case in cases) / max(len(cases), 1), 4)


def _provenance(item: dict[str, Any]) -> str:
    metadata: dict[str, Any] = (
        item["metadata"] if isinstance(item.get("metadata"), dict) else {}
    )
    return str(
        item.get("provenance")
        or item.get("source")
        or item.get("path")
        or metadata.get("provenance")
        or metadata.get("source")
        or ""
    )


def _project(item: dict[str, Any]) -> str:
    metadata: dict[str, Any] = (
        item["metadata"] if isinstance(item.get("metadata"), dict) else {}
    )
    return str(item.get("project") or metadata.get("project") or "")


def _thresholds(raw: Any) -> dict[str, float]:
    """Normalize optional suite gates without making legacy evals stricter."""
    defaults = {
        "precision_min": 0.0,
        "recall_min": 0.0,
        "mean_reciprocal_rank_min": 0.0,
        "stale_hit_rate_max": 1.0,
        "contradiction_hit_rate_max": 1.0,
        "project_scope_accuracy_min": 0.0,
        "explanation_coverage_min": 0.0,
        "provenance_coverage_min": 0.0,
        "backlink_coverage_min": 0.0,
        "budget_pass_rate_min": 1.0,
    }
    if not isinstance(raw, dict):
        return defaults
    for key in defaults:
        if key in raw:
            defaults[key] = max(0.0, min(1.0, float(raw[key])))
    return defaults


def _evaluate_thresholds(
    metrics: dict[str, float], thresholds: dict[str, float]
) -> dict[str, bool]:
    return {
        key: (
            metrics[key.removesuffix("_min")] >= value
            if key.endswith("_min")
            else metrics[key.removesuffix("_max")] <= value
        )
        for key, value in thresholds.items()
    }
