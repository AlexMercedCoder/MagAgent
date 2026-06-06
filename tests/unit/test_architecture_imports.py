from __future__ import annotations

import magent.tools as tools
from magent.cli import app as cli_app
from magent.cli import command_context
from magent.cli import main as cli_main
from magent.records import PlanRecord, PromotionCandidateRecord, TaskRecord
from magent.tools.executor import ToolExecutor as ExecutorImpl
from magent.tools.registry import tool_def
from magent.tools.types import DEFAULT_TOOL_BUDGETS, ToolResult
from magent.workbench import WorkbenchStore as WorkbenchStoreCompat
from magent.workbench import now_iso as now_iso_compat
from magent.workbench_domains import checkpoints, code_intel, patches, plans, project, release
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
    assert cli_main._known_command_names() == command_context.known_command_names(cli_app.app)
    command_names = {group.name for group in cli_app.app.registered_groups}
    assert {"memory", "task", "context", "release", "docs"} <= command_names


def test_workbench_domain_modules_expose_compatible_facades() -> None:
    import magent.workbench as workbench

    assert plans.save_plan is workbench.save_plan
    assert patches.save_patch is workbench.save_patch
    assert checkpoints.create_checkpoint is workbench.create_checkpoint
    assert project.project_doctor is workbench.project_doctor
    assert code_intel.code_index is workbench.code_index
    assert release.release_check is workbench.release_check


def test_tool_helper_modules_expose_executor_building_blocks() -> None:
    definition = tool_def("demo", "Demo tool", {"path": ("string", None)})

    assert definition["function"]["name"] == "demo"
    assert "path" in definition["function"]["parameters"]["required"]
    assert DEFAULT_TOOL_BUDGETS["read_file"] >= DEFAULT_TOOL_BUDGETS["default"]
    assert str(ToolResult).startswith("dict")


def test_typed_records_wrap_common_payload_shapes() -> None:
    task = TaskRecord.from_mapping({"id": "task_1", "title": "Docs"})
    plan = PlanRecord.from_mapping({"id": "plan_1", "goal": "Ship"})
    candidate = PromotionCandidateRecord.from_mapping(
        {
            "id": "promoted_task_docs",
            "source": "task",
            "source_id": "task_1",
            "title": "Docs",
            "type": "fact",
            "body": "# Docs",
            "tags": ["task"],
        }
    )

    assert task.status == "open"
    assert plan.status == "draft"
    assert candidate.to_memory_item()["links"] == []
