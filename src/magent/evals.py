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
    """Run a JSON eval suite's verification commands."""
    root_path = Path(root).resolve()
    path = Path(suite_path)
    if not path.is_absolute():
        path = root_path / path
    suite = _load_suite(path)
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
        "tasks": results,
        "ran_at": now_iso(),
    }
    if store is not None:
        store.append("eval_runs", report)
    return report


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
