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
