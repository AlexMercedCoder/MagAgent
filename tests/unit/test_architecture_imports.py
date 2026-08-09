from __future__ import annotations

import magent.tools as tools
import magent.tools.shell as shell_tools
import magent.tools.web as web_tools
from magent import memory_inbox, playbook, recipes, tool_packs, ui_actions
from magent.cli import app as cli_app
from magent.cli import command_context
from magent.cli import main as cli_main
from magent.cli.commands import browser, docs, evals, github
from magent.records import PlanRecord, PromotionCandidateRecord, TaskRecord
from magent.tools.artifacts import ArtifactToolsMixin
from magent.tools.catalog import built_in_tool_definitions, select_tool_definitions_for_message
from magent.tools.data import DataToolsMixin
from magent.tools.executor import ToolExecutor as ExecutorImpl
from magent.tools.files import FileToolsMixin
from magent.tools.registry import tool_def
from magent.tools.shell import ShellToolsMixin
from magent.tools.system import SystemToolsMixin
from magent.tools.types import DEFAULT_TOOL_BUDGETS, ToolResult
from magent.tools.web import WebToolsMixin
from magent.workbench import WorkbenchStore as WorkbenchStoreCompat
from magent.workbench import now_iso as now_iso_compat
from magent.workbench_domains import checkpoints, code_intel, patches, plans, project, release
from magent.workbench_store import WorkbenchStore, now_iso


def test_tool_executor_public_import_remains_compatible() -> None:
    assert tools.ToolExecutor is ExecutorImpl
    assert issubclass(ExecutorImpl, ArtifactToolsMixin)
    assert ExecutorImpl.create_docx.__module__ == "magent.tools.artifacts"
    assert ExecutorImpl.create_pptx.__module__ == "magent.tools.artifacts"
    assert ExecutorImpl.create_svg.__module__ == "magent.tools.artifacts"
    assert ExecutorImpl.create_diagram.__module__ == "magent.tools.artifacts"
    assert ExecutorImpl.create_image.__module__ == "magent.tools.artifacts"
    assert ExecutorImpl.generate_image.__module__ == "magent.tools.artifacts"
    assert issubclass(ExecutorImpl, ShellToolsMixin)
    assert ExecutorImpl.run_shell.__module__ == "magent.tools.shell"
    assert ExecutorImpl.run_python.__module__ == "magent.tools.shell"
    assert ExecutorImpl.install_package.__module__ == "magent.tools.shell"
    assert ExecutorImpl.search_codebase.__module__ == "magent.tools.shell"
    assert callable(shell_tools.execute_plan_sandbox)
    assert callable(shell_tools.sandbox_plan_preview)
    assert issubclass(ExecutorImpl, WebToolsMixin)
    assert ExecutorImpl.web_search.__module__ == "magent.tools.web"
    assert ExecutorImpl.web_fetch.__module__ == "magent.tools.web"
    assert ExecutorImpl.deep_research.__module__ == "magent.tools.web"
    assert ExecutorImpl.http_request.__module__ == "magent.tools.web"
    assert ExecutorImpl.browser_snapshot.__module__ == "magent.tools.web"
    assert ExecutorImpl.browser_screenshot.__module__ == "magent.tools.web"
    assert callable(web_tools.browser_snapshot)
    assert callable(web_tools.browser_screenshot)
    assert issubclass(ExecutorImpl, FileToolsMixin)
    assert ExecutorImpl.read_file.__module__ == "magent.tools.files"
    assert ExecutorImpl.read_file_range.__module__ == "magent.tools.files"
    assert ExecutorImpl.outline_file.__module__ == "magent.tools.files"
    assert ExecutorImpl.write_file.__module__ == "magent.tools.files"
    assert ExecutorImpl.edit_file.__module__ == "magent.tools.files"
    assert ExecutorImpl.delete_file.__module__ == "magent.tools.files"
    assert ExecutorImpl.list_dir.__module__ == "magent.tools.files"
    assert ExecutorImpl.diff_files.__module__ == "magent.tools.files"
    assert ExecutorImpl.compress.__module__ == "magent.tools.files"
    assert ExecutorImpl.extract.__module__ == "magent.tools.files"
    assert ExecutorImpl.magent_docs_search.__module__ == "magent.tools.files"
    assert issubclass(ExecutorImpl, DataToolsMixin)
    assert ExecutorImpl.json_query.__module__ == "magent.tools.data"
    assert ExecutorImpl.db_query.__module__ == "magent.tools.data"
    assert ExecutorImpl.db_execute.__module__ == "magent.tools.data"
    assert ExecutorImpl.db_list_tables.__module__ == "magent.tools.data"
    assert ExecutorImpl.db_schema.__module__ == "magent.tools.data"
    assert ExecutorImpl.db_list_databases.__module__ == "magent.tools.data"
    assert issubclass(ExecutorImpl, SystemToolsMixin)
    assert ExecutorImpl.system_info.__module__ == "magent.tools.system"
    assert ExecutorImpl.notify.__module__ == "magent.tools.system"
    assert ExecutorImpl.clipboard_read.__module__ == "magent.tools.system"
    assert ExecutorImpl.clipboard_write.__module__ == "magent.tools.system"
    assert ExecutorImpl.open_file.__module__ == "magent.tools.system"
    assert ExecutorImpl.read_image.__module__ == "magent.tools.system"
    assert ExecutorImpl.git_op.__module__ == "magent.tools.shell"
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
    assert {"memory", "task", "context", "release", "docs", "recipe", "tools"} <= command_names


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
    built_in_names = {item["function"]["name"] for item in built_in_tool_definitions()}
    browser_names = {
        item["function"]["name"]
        for item in select_tool_definitions_for_message(
            built_in_tool_definitions(),
            "take a browser screenshot",
        )
    }

    assert definition["function"]["name"] == "demo"
    assert "path" in definition["function"]["parameters"]["required"]
    assert {"write_file", "deep_research", "create_pptx"} <= built_in_names
    assert {"browser_snapshot", "browser_screenshot"} <= browser_names
    assert DEFAULT_TOOL_BUDGETS["read_file"] >= DEFAULT_TOOL_BUDGETS["default"]
    assert str(ToolResult).startswith("dict")


def test_cli_command_modules_register_extracted_groups() -> None:
    assert callable(browser.register_browser_commands)
    assert callable(docs.register_docs_commands)
    assert callable(evals.register_eval_commands)
    assert callable(github.register_github_commands)


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


def test_release_015_feature_modules_are_importable() -> None:
    assert recipes.BUILTIN_RECIPES["release-prep"]["commands"]
    assert playbook.PLAYBOOK_PATH.as_posix() == ".magent/playbook.toml"
    assert "web" in tool_packs.PACKS
    assert memory_inbox.DECISION_STORE == "memory_inbox_decisions"
    assert callable(ui_actions.inspect_patch)
