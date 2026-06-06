from __future__ import annotations

import magent.tools as tools
from magent.cli import app as cli_app
from magent.cli import main as cli_main
from magent.tools.executor import ToolExecutor as ExecutorImpl
from magent.workbench import WorkbenchStore as WorkbenchStoreCompat
from magent.workbench import now_iso as now_iso_compat
from magent.workbench_store import WorkbenchStore, now_iso


def test_tool_executor_public_import_remains_compatible() -> None:
    assert tools.ToolExecutor is ExecutorImpl
    assert hasattr(tools, "asyncio")
    assert hasattr(tools, "shutil")


def test_workbench_store_public_import_remains_compatible() -> None:
    assert issubclass(WorkbenchStoreCompat, WorkbenchStore)
    assert now_iso_compat is now_iso


def test_cli_app_composition_is_shared_with_main_entrypoint() -> None:
    assert cli_main.app is cli_app.app
    assert cli_main.memory_app is cli_app.memory_app
    command_names = {group.name for group in cli_app.app.registered_groups}
    assert {"memory", "task", "context", "release", "docs"} <= command_names
