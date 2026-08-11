"""Local performance diagnostics for MagAgent."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
from typing import Any

from magent import __version__
from magent.config import load_config, load_global_config
from magent.project_scan import scan_estimate
from magent.workbench_maintenance import workbench_stats

PERFORMANCE_BUDGETS: dict[str, dict[str, float]] = {
    "quick": {
        "cold_cli_import_ms_max": 1800.0,
        "project_inspection_ms_max": 1800.0,
        "memory_search_average_ms_max": 250.0,
        "event_write_per_second_min": 100.0,
        "event_read_1000_ms_max": 500.0,
        "four_concurrent_tasks_ms_max": 3000.0,
    },
    "release": {
        "cold_cli_import_ms_max": 1500.0,
        "project_inspection_ms_max": 1500.0,
        "memory_search_average_ms_max": 150.0,
        "event_write_per_second_min": 150.0,
        "event_read_1000_ms_max": 350.0,
        "four_concurrent_tasks_ms_max": 2000.0,
    },
}


def install_shape(samples: int = 3) -> dict[str, Any]:
    """Measure installed package bytes and cold CLI import time."""
    distribution = metadata.distribution("mag-agent")
    package_files = [path for path in (distribution.files or []) if "magent" in path.parts]
    package_bytes = 0
    for relative in package_files:
        path = Path(str(distribution.locate_file(relative)))
        if path.is_file():
            package_bytes += path.stat().st_size

    timings: list[float] = []
    probe = (
        "import json,time; start=time.perf_counter(); import magent.cli.main; "
        "print(json.dumps({'ms':(time.perf_counter()-start)*1000}))"
    )
    for _sample in range(max(1, min(samples, 10))):
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        timings.append(float(json.loads(completed.stdout.strip().splitlines()[-1])["ms"]))
    return {
        "ok": True,
        "version": __version__,
        "installed_distribution_version": distribution.version,
        "package_bytes": package_bytes,
        "cold_cli_import_ms": {
            "samples": [round(value, 2) for value in timings],
            "minimum": round(min(timings), 2),
            "average": round(sum(timings) / len(timings), 2),
        },
    }


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


def performance_budget(
    store: Any,
    username: str,
    project: str | Path = ".",
    *,
    profile: str = "quick",
) -> dict[str, Any]:
    """Exercise daily-driver hot paths and compare them with published budgets."""
    if profile not in PERFORMANCE_BUDGETS:
        raise ValueError(f"Unknown performance profile: {profile}")
    event_count = 10_000 if profile == "release" else 1_000
    install = install_shape(samples=1)
    doctor = performance_doctor(store, username, project)
    memory = _memory_search_benchmark(username)
    runtime = _task_runtime_benchmark(event_count)
    metrics = {
        "cold_cli_import_ms": float(install["cold_cli_import_ms"]["average"]),
        "project_inspection_ms": round(sum(doctor["timings_ms"].values()), 3),
        "memory_search_average_ms": memory["average_ms"],
        "event_write_per_second": runtime["event_write_per_second"],
        "event_read_1000_ms": runtime["event_read_1000_ms"],
        "four_concurrent_tasks_ms": runtime["four_concurrent_tasks_ms"],
    }
    budgets = PERFORMANCE_BUDGETS[profile]
    gates = {
        key: (
            metrics[key.removesuffix("_max")] <= limit
            if key.endswith("_max")
            else metrics[key.removesuffix("_min")] >= limit
        )
        for key, limit in budgets.items()
    }
    return _redact_home_paths(
        {
            "schema": "magent.performance-budget.v1",
            "ok": all(gates.values()),
            "profile": profile,
            "version": install["version"],
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
            },
            "workload": {"task_events": event_count, "concurrent_tasks": 4},
            "metrics": metrics,
            "budgets": budgets,
            "gates": gates,
            "details": {"install": install, "doctor": doctor, "memory": memory, "runtime": runtime},
        }
    )


def _redact_home_paths(value: Any) -> Any:
    """Keep shareable performance reports free of user-specific home paths."""
    home = str(Path.home())
    if isinstance(value, str):
        return value.replace(home, "~")
    if isinstance(value, dict):
        return {key: _redact_home_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_home_paths(item) for item in value]
    return value


def _memory_search_benchmark(username: str, samples: int = 10) -> dict[str, Any]:
    from magent.config import user_memory_dir
    from magent.memory import MemoryManager

    manager = MemoryManager(user_memory_dir(username), username=username)
    timings: list[float] = []
    result_count = 0
    for _ in range(samples):
        started = time.perf_counter()
        results = manager.search("current project decisions", max_results=5, mode="hybrid")
        timings.append(_elapsed_ms(started))
        result_count = max(result_count, len(results))
    return {
        "available": manager.available,
        "samples": samples,
        "average_ms": round(sum(timings) / max(len(timings), 1), 3),
        "maximum_ms": round(max(timings, default=0.0), 3),
        "result_count": result_count,
    }


def _task_runtime_benchmark(event_count: int) -> dict[str, Any]:
    from magent.task_runtime import TaskRuntime

    with tempfile.TemporaryDirectory(prefix="magent-performance-") as tmp:
        runtime = TaskRuntime(tmp)
        task = runtime.create("benchmark", "Event throughput benchmark", project=tmp)
        started = time.perf_counter()
        batch_size = min(100, event_count)
        for start in range(0, event_count, batch_size):
            runtime.record_events(
                task["id"],
                [
                    {"type": "benchmark.tick", "detail": {"index": index}}
                    for index in range(start, min(start + batch_size, event_count))
                ],
            )
        write_ms = _elapsed_ms(started)

        started = time.perf_counter()
        events = runtime.events(task["id"], after=max(0, event_count - 1000), limit=1000)
        read_ms = _elapsed_ms(started)

        def task_writer(index: int) -> int:
            worker = TaskRuntime(tmp)
            created = worker.create("benchmark", f"Concurrent writer {index}", project=tmp)
            for event_index in range(25):
                worker.record_event(
                    created["id"], "benchmark.concurrent", detail={"index": event_index}
                )
            return len(worker.events(created["id"], limit=100))

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent_counts = list(pool.map(task_writer, range(4)))
        concurrent_ms = _elapsed_ms(started)

    return {
        "events_written": event_count,
        "event_write_batch_size": batch_size,
        "event_write_ms": write_ms,
        "event_write_per_second": round(event_count / max(write_ms / 1000, 0.001), 2),
        "events_read": len(events),
        "event_read_1000_ms": read_ms,
        "four_concurrent_tasks_ms": concurrent_ms,
        "concurrent_event_counts": concurrent_counts,
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
    if int(workbench.get("total_bytes") or 0) > 10_000_000:
        items.append(
            {
                "severity": "info",
                "area": "workbench",
                "message": "Workbench state is over 10 MB; compact and prune to reduce startup diagnostics cost.",
                "command": "magent workbench compact && magent workbench prune --dry-run",
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
