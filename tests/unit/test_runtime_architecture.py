from __future__ import annotations

import ast
import json
from pathlib import Path

from magent.capability_readiness import CAPABILITY_MODULES, capability_readiness, readiness_report
from magent.task_runtime import TaskRuntime

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src" / "magent"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def test_domain_layers_do_not_depend_on_cli_or_ui() -> None:
    paths = [*SOURCE.glob("agent_runtime/*.py"), *SOURCE.glob("tools/*.py")]
    for path in paths:
        forbidden = {
            name for name in _imports(path) if name.startswith(("magent.cli", "magent.ui"))
        }
        assert not forbidden, f"{path.relative_to(ROOT)} imports presentation layer: {forbidden}"


def test_runtime_modules_stay_below_milestone_limit() -> None:
    for name in ("context.py", "lifecycle.py", "tool_loop.py"):
        path = SOURCE / "agent_runtime" / name
        assert len(path.read_text(encoding="utf-8").splitlines()) < 1000


def test_stable_task_contract_fixtures(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path)
    task = runtime.create("ask", "contract test", project=tmp_path)
    event = runtime.events(task["id"])[0]
    for filename, value in (("task-v2.json", task), ("task-event-v1.json", event)):
        fixture = json.loads((ROOT / "tests" / "fixtures" / "contracts" / filename).read_text())
        assert fixture["schema_version"] == value["schema_version"]
        assert set(fixture["required"]).issubset(value)


def test_optional_capability_report_has_actionable_installs(monkeypatch) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda _name: None)
    report = readiness_report()
    assert report["core_ready"] is True
    assert len(report["capabilities"]) == len(CAPABILITY_MODULES)
    for name in CAPABILITY_MODULES:
        item = capability_readiness(name)
        assert item.available is False
        assert f"mag-agent[{name}]" in item.install
