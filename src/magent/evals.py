"""Local benchmark and evaluation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from magent.command_policy import run_policy_checked_command
from magent.workbench_store import now_iso

EVALS_DIR = Path("evals")


def eval_template() -> str:
    return """{
  "name": "sample-python-repair",
  "description": "Small repo task that should be solved with focused edits and tests.",
  "tasks": [
    {
      "id": "unit-tests",
      "prompt": "Fix the failing unit tests without changing public behavior.",
      "commands": [{"argv": ["python", "-m", "pytest", "-q"]}],
      "success": ["command:0"]
    }
  ]
}
"""


def init_evals(root: str | Path = ".") -> dict[str, Any]:
    """Create a starter eval suite in ``evals/magagent-evals.json``."""
    target = Path(root).resolve() / EVALS_DIR / "magagent-evals.json"
    if target.exists():
        return {"ok": False, "error": f"Eval suite already exists: {target}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(eval_template(), encoding="utf-8")
    return {"ok": True, "path": str(target)}


def list_eval_suites(root: str | Path = ".") -> list[dict[str, Any]]:
    base = Path(root).resolve() / EVALS_DIR
    suites = []
    for path in sorted(base.glob("*.json")):
        suite = _load_suite(path)
        suites.append(
            {
                "name": suite.get("name", path.stem),
                "path": str(path),
                "tasks": len(suite.get("tasks", [])),
                "description": suite.get("description", ""),
            }
        )
    return suites


def run_eval_suite(root: str | Path, suite_path: str | Path, store: Any | None = None) -> dict[str, Any]:
    """Run a legacy verification suite or a real-agent eval suite."""
    root_path = Path(root).resolve()
    path = Path(suite_path)
    if not path.is_absolute():
        path = root_path / path
    suite = _load_suite(path)
    if suite.get("schema") == "magent.agent-eval.v1":
        from magent.agent_evals import run_agent_eval_suite

        return run_agent_eval_suite(root_path, path, store=store)
    results = []
    for task in suite.get("tasks", []):
        command_results = [_run_command(root_path, command) for command in task.get("commands", [])]
        ok = all(item["ok"] for item in command_results)
        results.append(
            {
                "id": task.get("id", ""),
                "prompt": task.get("prompt", ""),
                "ok": ok,
                "commands": command_results,
            }
        )
    report = {
        "ok": all(item["ok"] for item in results),
        "suite": suite.get("name", path.stem),
        "path": str(path),
        "root": str(root_path),
        "version": _current_version(),
        "passed": sum(1 for item in results if item["ok"]),
        "total": len(results),
        "tasks": results,
        "ran_at": now_iso(),
    }
    if store is not None:
        store.append("eval_runs", report)
    return report


def _current_version() -> str:
    try:
        from magent import __version__

        return str(__version__)
    except Exception:
        return ""


def compare_eval_runs(
    store: Any,
    suite: str,
    baseline: str,
    *,
    collection: str = "eval_runs",
) -> dict[str, Any]:
    """Compare the latest run of `suite` against the last run at `baseline`.

    Lets a release claim measured capability instead of asserting it: the
    roadmap's `magent eval run --compare v0.34.0`.
    """
    runs = [item for item in store.read(collection, []) if item.get("suite") == suite]
    if not runs:
        return {"ok": False, "error": f"No recorded runs for suite {suite!r}"}

    latest = runs[-1]
    previous = next(
        (item for item in reversed(runs[:-1]) if str(item.get("version", "")) == baseline), None
    )
    if previous is None:
        return {
            "ok": False,
            "error": f"No run of {suite!r} recorded at version {baseline!r}",
            "known_versions": sorted({str(item.get("version", "")) for item in runs if item.get("version")}),
        }

    def outcomes(run: dict[str, Any]) -> dict[str, bool]:
        return {str(task.get("id", "")): bool(task.get("ok")) for task in run.get("tasks", [])}

    before, after = outcomes(previous), outcomes(latest)
    regressions = sorted(task for task, ok in after.items() if before.get(task) and not ok)
    fixes = sorted(task for task, ok in after.items() if ok and before.get(task) is False)

    return {
        # A regression is a failure of the comparison, whatever the totals say.
        "ok": not regressions,
        "suite": suite,
        "baseline": baseline,
        "baseline_ran_at": previous.get("ran_at", ""),
        "current_version": latest.get("version", ""),
        "current_ran_at": latest.get("ran_at", ""),
        "baseline_passed": f"{previous.get('passed', 0)}/{previous.get('total', 0)}",
        "current_passed": f"{latest.get('passed', 0)}/{latest.get('total', 0)}",
        "regressions": regressions,
        "fixed": fixes,
        "new_tasks": sorted(set(after) - set(before)),
        "removed_tasks": sorted(set(before) - set(after)),
    }


def eval_report(store: Any, limit: int = 20) -> list[dict[str, Any]]:
    return list(reversed(store.read("eval_runs", [])))[:limit]


def _load_suite(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _run_command(root: Path, command: Any) -> dict[str, Any]:
    result = run_policy_checked_command(command, cwd=root, timeout=300)
    if "stdout" in result:
        result["stdout"] = str(result.get("stdout", ""))[-3000:]
        result["stderr"] = str(result.get("stderr", ""))[-3000:]
    return result
