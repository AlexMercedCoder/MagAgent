"""Local performance diagnostics for MagAgent."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from magent.config import load_config, load_global_config
from magent.project_scan import scan_estimate
from magent.workbench_maintenance import workbench_stats


def performance_doctor(store: Any, username: str, project: str | Path = ".") -> dict[str, Any]:
    """Return lightweight diagnostics for local runtime cost and storage growth."""
    root = Path(project).resolve()
    timings: dict[str, float] = {}

    start = time.perf_counter()
    global_cfg = load_global_config()
    timings["load_global_config_ms"] = _elapsed_ms(start)

    start = time.perf_counter()
    config = load_config(username)
    timings["load_merged_config_ms"] = _elapsed_ms(start)

    start = time.perf_counter()
    repo = scan_estimate(root, limit=5000)
    timings["repo_scan_estimate_ms"] = _elapsed_ms(start)

    start = time.perf_counter()
    workbench = workbench_stats(store)
    timings["workbench_stats_ms"] = _elapsed_ms(start)

    semantic = _semantic_status(username)
    recommendations = _recommendations(global_cfg, config, repo, workbench, semantic, timings)
    return {
        "ok": not any(item["severity"] == "error" for item in recommendations),
        "project": str(root),
        "timings_ms": timings,
        "repo": repo,
        "workbench": workbench,
        "semantic_memory": semantic,
        "config": {
            "memory_budget_tokens": config.memory_budget_tokens,
            "repo_map_budget_tokens": config.repo_map_budget_tokens,
            "semantic_memory_enabled": config.semantic_memory_enabled,
            "write_every_n_turns": config.write_every_n_turns,
            "selective_tools": config.selective_tools,
        },
        "recommendations": recommendations,
    }


def _semantic_status(username: str) -> dict[str, Any]:
    try:
        from magent.config import load_config, user_memory_dir
        from magent.semantic_memory import SemanticMemoryIndex

        config = load_config(username)
        index = SemanticMemoryIndex(
            username,
            user_memory_dir(username),
            provider=config.semantic_memory_provider,
            model=config.semantic_memory_model,
        )
        return index.status()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _recommendations(
    global_cfg: dict[str, Any],
    config: Any,
    repo: dict[str, Any],
    workbench: dict[str, Any],
    semantic: dict[str, Any],
    timings: dict[str, float],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if repo.get("truncated"):
        items.append(
            {
                "severity": "warn",
                "area": "repo",
                "message": "Project scan hit the 5000-file estimate limit.",
                "command": "magent profile apply lightweight",
            }
        )
    if workbench.get("recommendations"):
        items.append(
            {
                "severity": "warn",
                "area": "workbench",
                "message": "; ".join(workbench["recommendations"][:3]),
                "command": "magent workbench prune --dry-run",
            }
        )
    if int(semantic.get("chunks") or 0) > 10000:
        items.append(
            {
                "severity": "warn",
                "area": "semantic-memory",
                "message": "Semantic memory index has more than 10000 chunks.",
                "command": "magent memory semantic status",
            }
        )
    if timings.get("repo_scan_estimate_ms", 0) > 750:
        items.append(
            {
                "severity": "info",
                "area": "repo",
                "message": "Repo scan estimate is relatively slow.",
                "command": "magent profile apply lightweight",
            }
        )
    if config.repo_map_budget_tokens > 2000:
        items.append(
            {
                "severity": "info",
                "area": "config",
                "message": "Repo map budget is generous; lower it on constrained machines.",
                "command": "magent profile apply lightweight",
            }
        )
    if not global_cfg.get("agent", {}).get("selective_tools", True):
        items.append(
            {
                "severity": "warn",
                "area": "tools",
                "message": "Selective tool loading is disabled.",
                "command": "magent doctor --fix",
            }
        )
    return items


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)
