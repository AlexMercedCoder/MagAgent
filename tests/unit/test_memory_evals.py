from __future__ import annotations

import json
from pathlib import Path

from magent.memory_evals import run_memory_eval


class FakeMemory:
    budget_tokens = 100

    def search(self, query, max_results, mode):
        assert mode == "hybrid"
        return [
            {"id": "current", "reason": "lexical match"},
            {"id": "noise", "reason": "graph relationship"},
        ]

    def recall(self, query):
        return "Current project decision."


def test_memory_eval_reports_quality_and_budget_metrics(tmp_path: Path) -> None:
    suite = tmp_path / "memory-eval.json"
    suite.write_text(
        json.dumps(
            {
                "name": "memory-smoke",
                "cases": [
                    {
                        "id": "decision",
                        "query": "project decision",
                        "expected_ids": ["current"],
                        "forbidden_ids": ["stale"],
                        "max_context_tokens": 20,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_memory_eval(FakeMemory(), suite)

    assert report["ok"] is True
    assert report["metrics"]["precision"] == 0.5
    assert report["metrics"]["recall"] == 1.0
    assert report["metrics"]["stale_hit_rate"] == 0.0
    assert report["metrics"]["explanation_coverage"] == 1.0
    assert report["metrics"]["budget_pass_rate"] == 1.0
    assert report["metrics"]["mean_reciprocal_rank"] == 1.0
    assert report["schema"] == "magent.memory-eval.v2"


def test_memory_eval_enforces_scope_provenance_backlinks_and_thresholds(tmp_path: Path) -> None:
    class RichMemory(FakeMemory):
        def search(self, query, max_results, mode):
            return [
                {
                    "id": "current",
                    "reason": "project and recency match",
                    "project": "demo",
                    "source": "session/session_7",
                    "backlinks": ["decision_parent"],
                }
            ]

    suite = tmp_path / "memory-quality.json"
    suite.write_text(
        json.dumps(
            {
                "name": "release-memory",
                "thresholds": {
                    "precision_min": 1.0,
                    "recall_min": 1.0,
                    "mean_reciprocal_rank_min": 1.0,
                    "stale_hit_rate_max": 0.0,
                    "contradiction_hit_rate_max": 0.0,
                    "project_scope_accuracy_min": 1.0,
                    "explanation_coverage_min": 1.0,
                    "provenance_coverage_min": 1.0,
                    "backlink_coverage_min": 1.0,
                },
                "cases": [
                    {
                        "id": "scoped-decision",
                        "query": "decision",
                        "expected_ids": ["current"],
                        "stale_ids": ["old"],
                        "contradiction_ids": ["wrong"],
                        "expected_project": "demo",
                        "require_provenance": True,
                        "require_backlinks": True,
                        "max_context_tokens": 20,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_memory_eval(RichMemory(), suite)

    assert report["ok"] is True
    assert all(report["gates"].values())
    assert report["metrics"]["provenance_coverage"] == 1.0
    assert report["metrics"]["backlink_coverage"] == 1.0


def test_memory_eval_rejects_stale_or_contradictory_recall(tmp_path: Path) -> None:
    class StaleMemory(FakeMemory):
        def search(self, query, max_results, mode):
            return [{"id": "old", "reason": "lexical"}]

    suite = tmp_path / "stale.json"
    suite.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "query": "decision",
                        "expected_ids": ["current"],
                        "stale_ids": ["old"],
                        "contradiction_ids": ["old"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = run_memory_eval(StaleMemory(), suite)

    assert report["ok"] is False
    assert report["cases"][0]["requirements_ok"] is False
    assert report["metrics"]["stale_hit_rate"] == 1.0
