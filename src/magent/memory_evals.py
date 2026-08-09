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
    return {
        "ok": bool(cases) and all(case["budget_ok"] for case in cases),
        "suite": suite.get("name", path.stem),
        "path": str(path),
        "cases": cases,
        "metrics": {
            "precision": _average(cases, "precision"),
            "recall": _average(cases, "recall"),
            "stale_hit_rate": _average(cases, "stale_hit_rate"),
            "explanation_coverage": _average(cases, "explanation_coverage"),
            "average_context_tokens": round(
                sum(int(case["context_tokens"]) for case in cases) / max(count, 1), 2
            ),
            "budget_pass_rate": round(
                sum(bool(case["budget_ok"]) for case in cases) / max(count, 1), 4
            ),
        },
        "ran_at": now_iso(),
    }


def _run_case(memory_manager: Any, case: dict[str, Any]) -> dict[str, Any]:
    query = str(case.get("query") or "")
    limit = max(1, int(case.get("limit") or 5))
    expected = {str(item) for item in case.get("expected_ids", [])}
    forbidden = {str(item) for item in case.get("forbidden_ids", [])}
    results = memory_manager.search(query, max_results=limit, mode="hybrid")
    ids = [str(item.get("id") or "") for item in results if item.get("id")]
    relevant = len(expected.intersection(ids))
    stale = len(forbidden.intersection(ids))
    context = memory_manager.recall(query)
    context_tokens = estimate_tokens(context)
    budget = max(1, int(case.get("max_context_tokens") or memory_manager.budget_tokens))
    explained = sum(bool(item.get("reason") or item.get("reasons")) for item in results)
    return {
        "id": str(case.get("id") or query[:60]),
        "query": query,
        "result_ids": ids,
        "precision": round(relevant / max(len(ids), 1), 4),
        "recall": round(relevant / max(len(expected), 1), 4),
        "stale_hit_rate": round(stale / max(len(ids), 1), 4),
        "explanation_coverage": round(explained / max(len(results), 1), 4),
        "context_tokens": context_tokens,
        "max_context_tokens": budget,
        "budget_ok": context_tokens <= budget,
    }


def _average(cases: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(case[key]) for case in cases) / max(len(cases), 1), 4)
