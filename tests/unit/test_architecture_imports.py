from __future__ import annotations

import magent.tools as tools
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
