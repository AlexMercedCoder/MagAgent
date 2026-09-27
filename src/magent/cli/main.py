"""MagAgent CLI: the `magent` entry point.

Commands live in ``magent.cli.commands.*`` modules; shared helpers in
``magent.cli.shared``. Importing this module registers every command on
``app``.
"""

from __future__ import annotations

import os

import typer

from magent import __version__
from magent.cli import command_context, shared
from magent.cli.app import (
    agent_app,
    app,
    browser_app,
    config_app,
    daemon_app,
    docs_app,
    eval_app,
    events_app,
    execution_app,
    github_app,
    graph_app,
    hook_app,
    lsp_app,
    memory_app,
    memory_semantic_app,
    performance_app,
    permission_app,
    plugin_app,
    profile_app,
    provider_app,
    tools_app,
    user_app,
    webmcp_app,
    workbench_app,
)
from magent.cli.command_context import (
    known_command_names,
    require_user,
    store,
)
from magent.cli.commands.agents import register_agent_commands
from magent.cli.commands.browser import register_browser_commands
from magent.cli.commands.config import register_config_commands
from magent.cli.commands.daemon import register_daemon_commands
from magent.cli.commands.docs import register_docs_commands
from magent.cli.commands.evals import register_eval_commands
from magent.cli.commands.events import register_event_commands
from magent.cli.commands.execution import register_execution_commands
from magent.cli.commands.github import register_github_commands
from magent.cli.commands.graph import register_graph_commands
from magent.cli.commands.hooks import register_hook_commands
from magent.cli.commands.lsp import register_lsp_commands
from magent.cli.commands.memory import register_memory_commands
from magent.cli.commands.performance import register_performance_commands
from magent.cli.commands.permissions import register_permission_commands
from magent.cli.commands.plugins import register_plugin_commands
from magent.cli.commands.profiles import register_profile_commands
from magent.cli.commands.providers import register_provider_ux_commands
from magent.cli.commands.tools import register_tool_commands
from magent.cli.commands.workbench import register_workbench_commands

# Compatibility re-exports for callers that used these from magent.cli.main.
from magent.cli.shared import (  # noqa: F401
    MAX_PROMPT_FILE_BYTES,
    _await_with_progress,
    _block_until_interrupt,
    _build_and_save_plan,
    _build_extraction_provider,
    _build_provider,
    _emit_machine_json,
    _handle_slash_command,
    _known_command_names,
    _one_shot_events,
    _print_why_last,
    _require_user,
    _research_report_markdown,
    _resolve_ask_task,
    _resolve_cli_profile,
    _review_session_message,
    _run_one_shot,
    _run_one_shot_inner,
    _run_repl,
    _slugify_filename,
    _store,
    _write_research_report,
    console,
)
from magent.config import (
    load_config,
)

register_agent_commands(agent_app)

register_browser_commands(browser_app, webmcp_app)

register_provider_ux_commands(provider_app)

register_profile_commands(profile_app, store=store, console=console)

register_config_commands(config_app)

register_daemon_commands(daemon_app)

register_docs_commands(docs_app, known_command_names=lambda: known_command_names(app))

register_eval_commands(eval_app, store=store)

register_event_commands(events_app)

register_execution_commands(execution_app, store=store, console=console)

register_graph_commands(graph_app, store=store, console=console)

register_github_commands(github_app)

register_hook_commands(hook_app)

register_lsp_commands(lsp_app)

register_permission_commands(permission_app)

register_performance_commands(performance_app)

register_plugin_commands(plugin_app)

register_workbench_commands(workbench_app)

register_tool_commands(
    tools_app,
    store=lambda: shared._store(),
    load_active_config=lambda: load_config(require_user()),
    console=console,
)

register_memory_commands(
    memory_app,
    memory_semantic_app,
    user_app,
    # Late-bound on purpose: these resolve from this module's globals on each
    # call, so patching `cli_main._store` still reaches the extracted commands.
    store=lambda: shared._store(),
    require_user=lambda: shared._require_user(),
    get_memory_manager=lambda: command_context._get_memory_manager(),
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    task: str | None = typer.Option(None, "--task", "-t", help="Optional one-shot task to run"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="Provider ID"),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name"),
    project: str | None = typer.Option(None, "--project", help="Project directory"),
    agent: str | None = typer.Option(None, "--agent", help="Run with a named OAP agent profile"),
    version: bool = typer.Option(False, "--version", "-v", help="Show version"),
):
    """
    Start an interactive MagAgent session, or run a subcommand.
    """
    if version:
        console.print(f"MagAgent {__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        return

    # No subcommand — launch interactive REPL
    username = shared._require_user()
    config = load_config(username)
    cwd = project or os.getcwd()
    effective_profile = shared._resolve_cli_profile(agent, cwd, config)
    main_provider = shared._build_provider(
        config,
        provider or (effective_profile.provider if effective_profile else None),
        model or (effective_profile.model if effective_profile else None),
    )
    extract_provider = shared._build_extraction_provider(config)

    if task:
        shared._run_one_shot(
            username, config, main_provider, extract_provider, cwd, task, profile=effective_profile
        )
    else:
        shared._run_repl(
            username, config, main_provider, extract_provider, cwd, profile=effective_profile
        )


def _register_command_modules() -> None:
    """Import the command modules; their decorators register on ``app``."""
    import importlib

    for name in (
        "toplevel",
        "plans",
        "workbench_cmds",
        "system_cmds",
        "models",
        "sessions",
        "gateway",
        "mcp_servers",
    ):
        importlib.import_module(f"magent.cli.commands.{name}")


_register_command_modules()
