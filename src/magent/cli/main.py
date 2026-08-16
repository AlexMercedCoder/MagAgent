"""MagAgent CLI — main entry point and command groups."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from magent import __version__
from magent.cli import command_context
from magent.cli.app import (
    agent_app,
    api_app,
    app,
    artifact_app,
    auth_app,
    browser_app,
    cache_app,
    checkpoint_app,
    code_app,
    config_app,
    context_app,
    daemon_app,
    data_app,
    docs_app,
    eval_app,
    events_app,
    execution_app,
    followup_app,
    gateway_app,
    github_app,
    graph_app,
    hook_app,
    inbox_app,
    knowledge_app,
    lsp_app,
    mcp_app,
    memory_app,
    memory_semantic_app,
    model_app,
    patch_app,
    performance_app,
    permission_app,
    plugin_app,
    policy_app,
    profile_app,
    project_app,
    provider_app,
    recipe_app,
    release_app,
    routine_app,
    session_app,
    skill_app,
    subagent_app,
    system_app,
    task_app,
    test_app,
    tools_app,
    user_app,
    workbench_app,
    workspace_app,
)
from magent.cli.command_context import (
    ProviderCredentialError,
    build_extraction_provider,
    build_provider,
    build_provider_for_role,
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
from magent.cli.render import (
    _print_config_center,
    _print_context_map,
    _print_jobs_summary,
    _print_memory_stats,
    _print_orchestrated_preview,
    _print_orchestrated_run_result,
    _print_recent_insights,
    _print_research_result,
    _print_session_inbox,
    _print_session_peers,
    _print_session_receipt,
    _print_session_receipts,
    _print_session_usage,
)
from magent.config import (
    CONFIG_DIR,
    get_current_user,
    load_config,
)
from magent.prompt_input import read_multiline_prompt, read_user_prompt

console = Console()
register_agent_commands(agent_app)
register_browser_commands(browser_app)
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
    store=lambda: _store(),
    load_active_config=lambda: load_config(require_user()),
    console=console,
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _require_user() -> str:
    return require_user()


def _build_provider(config, provider_id: str | None, model: str | None):
    try:
        return build_provider(config, provider_id, model)
    except ProviderCredentialError as exc:
        console.print(f"[red]Provider not ready:[/red] {exc}")
        raise typer.Exit(1) from exc


def _build_extraction_provider(config):
    try:
        return build_extraction_provider(config)
    except ProviderCredentialError as exc:
        console.print(f"[red]Memory extraction provider not ready:[/red] {exc}")
        raise typer.Exit(1) from exc


def _resolve_cli_profile(name: str | None, cwd: str, config):
    explicit = name is not None
    selected = str(name or "").strip()
    if explicit and selected.lower() in {"none", "off"}:
        return None
    from magent.agent_profiles.effective import resolve_effective_profile
    from magent.agent_profiles.registry import AgentProfileRegistry
    from magent.tools.catalog import built_in_tool_definitions

    selected = selected or str(getattr(config, "default_agent_profile", "magagent") or "magagent")
    resolved = AgentProfileRegistry(cwd, config).get(selected)
    if resolved is None and not explicit and selected != "magagent":
        console.print(
            f"[yellow]Default agent profile '{selected}' is unavailable here; using magagent.[/yellow]"
        )
        selected = "magagent"
        resolved = AgentProfileRegistry(cwd, config).get(selected)
    if resolved is None:
        console.print(f"[red]Agent profile not found:[/red] {selected}")
        raise typer.Exit(1)
    granted = {item.get("function", {}).get("name", "") for item in built_in_tool_definitions()}
    return resolve_effective_profile(resolved, config, granted)


def _store():
    return store()


def _known_command_names() -> list[str]:
    return known_command_names(app)


# ─────────────────────────────────────────────
# Root commands
# ─────────────────────────────────────────────


@system_app.command("info")
def system_info_cmd(json_output: bool = typer.Option(True, "--json/--no-json")):
    """Return machine-readable MagAgent installation and path info."""
    from magent.desktop_api import system_info

    data = system_info()
    if json_output:
        console.print_json(data=data)
        return
    table = Table("Key", "Value")
    table.add_row("MagAgent", data["magent_version"])
    table.add_row("Python", data["python"])
    table.add_row("User", str(data["current_user"]))
    table.add_row("Config", data["paths"]["config_dir"])
    console.print(table)


@system_app.command("contracts")
def system_contracts_cmd() -> None:
    """Return versioned machine APIs and compatibility policy."""
    from magent.desktop_api import platform_contracts

    console.print_json(data=platform_contracts())


@system_app.command("compatibility")
def system_compatibility_cmd() -> None:
    """Inventory the proposed 1.0 stable, beta, and experimental surfaces."""
    from magent.contract_inventory import contract_inventory

    console.print_json(data=contract_inventory(_known_command_names()))


@system_app.command("migrate")
def system_migrate_cmd(
    root: str = typer.Option(str(CONFIG_DIR), "--root"),
    apply: bool = typer.Option(False, "--apply", help="Apply after creating a private backup."),
    backup_dir: str = typer.Option("", "--backup-dir"),
) -> None:
    """Preview or apply backup-first persistent-state migrations."""
    from magent.migrations import migrate_state

    result = migrate_state(root, apply=apply, backup_dir=backup_dir or None)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@system_app.command("rollback")
def system_rollback_cmd(
    backup: str = typer.Argument(...),
    root: str = typer.Option(str(CONFIG_DIR), "--root"),
    apply: bool = typer.Option(False, "--apply", help="Restore the inspected backup."),
) -> None:
    """Preview or restore a migration backup with path-containment checks."""
    from magent.migrations import rollback_state

    result = rollback_state(root, backup, apply=apply)
    console.print_json(data=result)


@system_app.command("security-report")
def system_security_report_cmd(
    output: str | None = typer.Option(None, "--output", "-o", help="Write the JSON report."),
) -> None:
    """Run credential-free security boundary probes."""
    from magent.security_assurance import (
        security_assurance_report,
        write_security_assurance_report,
    )

    report = security_assurance_report()
    if output:
        report["saved_to"] = write_security_assurance_report(report, output)
    console.print_json(data=report)
    if not report["ok"]:
        raise typer.Exit(1)


@system_app.command("ecosystem-report")
def system_ecosystem_report_cmd(
    root: str = typer.Option(".", "--root", help="Mag ecosystem workspace or MagAgent checkout."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Write the JSON report to this path."
    ),
) -> None:
    """Generate deterministic local evidence and list external release gates."""
    from magent.ecosystem_readiness import ecosystem_readiness, write_ecosystem_report

    report = ecosystem_readiness(root)
    if output:
        report["saved_to"] = str(write_ecosystem_report(report, output))
    console.print_json(data=report)
    if not report.get("ok"):
        raise typer.Exit(1)


@cache_app.command("doctor")
def cache_doctor_cmd(
    provider: str | None = typer.Option(None, "--provider", "-p"),
    model: str | None = typer.Option(None, "--model", "-m"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show prompt-cache readiness for the current provider/model."""
    from magent.agent import AGENT_STATIC_PROMPT
    from magent.cache import cache_doctor_data

    username = get_current_user()
    config = load_config(username)
    provider_id = provider or config.default_provider
    model_name = model or config.default_model
    data = cache_doctor_data(provider_id, model_name, AGENT_STATIC_PROMPT, "", config)
    if json_output:
        console.print_json(data=data)
        return
    table = Table("Field", "Value")
    table.add_row("Provider", provider_id)
    table.add_row("Model", model_name)
    table.add_row("Enabled", str(data["enabled"]))
    table.add_row("Stable prefix tokens", str(data["stable_prefix_tokens"]))
    table.add_row("Request hints", ", ".join(sorted(data["request_hints"])) or "none")
    table.add_row("Known usage fields", ", ".join(data["capabilities"]["usage_fields"]) or "none")
    console.print(table)
    recommendations = data.get("recommendations") or []
    if recommendations:
        console.print("[bold]Recommendations[/bold]")
        for item in recommendations:
            console.print(f"- {item}")
    else:
        console.print("[green]Prompt cache setup looks reasonable.[/green]")


@cache_app.command("status")
def cache_status_cmd(json_output: bool = typer.Option(False, "--json")):
    """Summarize recorded prompt-cache usage from local session logs."""
    from magent.workbench import usage_stats

    stats = usage_stats()
    prompt_tokens = int(stats.get("prompt_tokens") or 0)
    cached_tokens = int(stats.get("cached_tokens") or 0)
    data = {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        "cache_write_tokens": int(stats.get("cache_write_tokens") or 0),
        "cache_miss_tokens": int(stats.get("cache_miss_tokens") or 0),
        "sessions": int(stats.get("sessions") or 0),
    }
    if json_output:
        console.print_json(data=data)
        return
    table = Table("Metric", "Value")
    for key, value in data.items():
        table.add_row(key, str(value))
    console.print(table)


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
    username = _require_user()
    config = load_config(username)
    cwd = project or os.getcwd()
    effective_profile = _resolve_cli_profile(agent, cwd, config)
    main_provider = _build_provider(
        config,
        provider or (effective_profile.provider if effective_profile else None),
        model or (effective_profile.model if effective_profile else None),
    )
    extract_provider = _build_extraction_provider(config)

    if task:
        _run_one_shot(
            username, config, main_provider, extract_provider, cwd, task, profile=effective_profile
        )
    else:
        _run_repl(username, config, main_provider, extract_provider, cwd, profile=effective_profile)


@app.command("ask", rich_help_panel="Everyday Agent Work")
def ask_cmd(
    task: str = typer.Argument(..., help="One-shot task to run non-interactively"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="Provider ID"),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name"),
    project: str | None = typer.Option(None, "--project", help="Project directory"),
    agent: str | None = typer.Option(None, "--agent", help="Run with a named OAP agent profile"),
    permission_mode: str | None = typer.Option(
        None,
        "--permission-mode",
        help="Override permission mode for this run: silent, balanced, paranoid, or yolo.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Approve eligible tool actions non-interactively by using yolo permission mode.",
    ),
    repair_attempts: int = typer.Option(
        0,
        "--repair-attempts",
        min=0,
        max=3,
        help="Retry obvious incomplete file tasks after audit warnings.",
    ),
    strict_audit: bool = typer.Option(
        False,
        "--strict-audit",
        help="Exit nonzero when the one-shot task audit reports missing files or blocked tools.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable response, audit, and tool summary.",
    ),
    events: bool = typer.Option(
        False,
        "--events",
        help="Include structured desktop event records in JSON output.",
    ),
    execution_task_id: str = typer.Option(
        "",
        "--execution-task-id",
        hidden=True,
        help="Attach this run to a pre-created durable execution task.",
    ),
):
    """Run a one-shot MagAgent task."""
    username = _require_user()
    config = load_config(username)
    permission_override = permission_mode
    if yes:
        permission_override = "yolo"
    cwd = project or os.getcwd()
    effective_profile = _resolve_cli_profile(agent, cwd, config)
    main_provider = _build_provider(
        config,
        provider or (effective_profile.provider if effective_profile else None),
        model or (effective_profile.model if effective_profile else None),
    )
    extract_provider = _build_extraction_provider(config)
    _run_one_shot(
        username,
        config,
        main_provider,
        extract_provider,
        cwd,
        task,
        permission_mode_override=permission_override,
        repair_attempts=repair_attempts,
        strict_audit=strict_audit,
        json_output=json_output,
        events_output=events,
        execution_task_id=execution_task_id,
        profile=effective_profile,
    )


def _run_one_shot(
    username,
    config,
    main_provider,
    extract_provider,
    cwd,
    task,
    permission_mode_override: str | None = None,
    repair_attempts: int = 0,
    strict_audit: bool = False,
    json_output: bool = False,
    events_output: bool = False,
    execution_task_id: str = "",
    profile=None,
):
    """Run a single non-interactive agent task."""
    from magent.agent import AgentSession
    from magent.execution_bridge import SessionTaskBridge
    from magent.tui import print_response

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
        interactive_permissions=False,
        permission_mode_override=permission_mode_override,
        profile=profile,
    )
    bridge = SessionTaskBridge(
        _store(),
        session,
        kind="ask",
        title=task,
        project=cwd,
        permission_policy=permission_mode_override or config.permission_mode,
        provider=main_provider,
        task_id=execution_task_id,
        metadata={"source": "cli.ask"},
    )
    execution_task_id = bridge.task_id

    from magent.ask_audit import audit_one_shot_task, render_audit_note

    final_audit = {}

    async def _run() -> str:
        nonlocal final_audit
        try:
            response = await _await_with_progress(
                session.chat(task),
                "MagAgent is working on your task",
                enabled=not json_output,
            )
            final_audit = audit_one_shot_task(task, cwd, session.scratchpad)
            attempts = 0
            while attempts < repair_attempts and not final_audit["ok"]:
                attempts += 1
                repair_prompt = (
                    "The previous one-shot run appears incomplete. "
                    f"Audit: {json.dumps(final_audit, default=str)}\n"
                    "Use available tools to finish only the missing or blocked parts. "
                    "If a permission-required tool was blocked, choose a safer available tool or explain the blocker."
                )
                repair_response = await _await_with_progress(
                    session.chat(repair_prompt),
                    f"Repair attempt {attempts} is running",
                    enabled=not json_output,
                )
                response += "\n\nRepair attempt " + str(attempts) + ":\n" + repair_response
                final_audit = audit_one_shot_task(task, cwd, session.scratchpad)
            return response
        finally:
            await session.end_session()

    try:
        response = asyncio.run(_run())
    except BaseException as exc:
        bridge.fail(exc)
        raise
    bridge.complete(final_audit)
    if json_output:
        payload = {
            "ok": bool(final_audit.get("ok", True)),
            "response": response,
            "audit": final_audit,
            "scratchpad": {
                "files_touched": session.scratchpad.get("files_touched", []),
                "commands_run": session.scratchpad.get("commands_run", []),
                "permission_failures": session.scratchpad.get("permission_failures", []),
            },
            "session_id": session.session_id,
            "execution_task_id": execution_task_id,
        }
        if events_output:
            payload["events"] = _one_shot_events(task, response, final_audit, session)
        console.print_json(data=payload)
    else:
        response += render_audit_note(final_audit)
        print_response(response)
    if strict_audit and final_audit and not final_audit.get("ok"):
        raise typer.Exit(1)


async def _await_with_progress(coro, message: str, *, enabled: bool = True):
    """Await a coroutine while periodically showing one-shot CLI progress."""
    if not enabled:
        return await coro
    task = asyncio.create_task(coro)
    started = time.monotonic()
    next_update = 0.0
    while not task.done():
        elapsed = time.monotonic() - started
        if elapsed >= next_update:
            if elapsed < 1:
                console.print(f"[dim]{message}...[/dim]")
            else:
                console.print(f"[dim]{message}... {int(elapsed)}s elapsed[/dim]")
            next_update = elapsed + 8
        await asyncio.sleep(0.25)
    return await task


@app.command("research", rich_help_panel="Everyday Agent Work")
def research_cmd(
    topic: str = typer.Argument(..., help="Research topic or question."),
    question: Annotated[
        list[str] | None,
        typer.Option("--question", "-q", help="Optional focused research question."),
    ] = None,
    max_sources: int = typer.Option(6, "--max-sources", "-n", min=1, max=20),
    fetch_sources: bool = typer.Option(
        True, "--fetch/--no-fetch", help="Fetch and excerpt source pages."
    ),
    json_output: bool = typer.Option(False, "--json/--no-json"),
    write: bool | None = typer.Option(
        None,
        "--write/--no-write",
        help="Write a Markdown research report in the active directory.",
    ),
    out: str | None = typer.Option(None, "--out", "-o", help="Output path for --write."),
):
    """Run deep web research without starting a full agent session."""
    from magent.tools import ToolExecutor

    async def _run() -> dict:
        tools = ToolExecutor(os.getcwd(), permission_mode="silent", interactive_permissions=False)
        return await tools.deep_research(
            topic,
            questions=question or [],
            max_sources=max_sources,
            fetch_sources=fetch_sources,
        )

    result = asyncio.run(_run())
    if json_output:
        console.print_json(data=result)
    else:
        _print_research_result(result)
        should_write = write
        if should_write is None and sys.stdin.isatty() and result.get("ok"):
            should_write = Confirm.ask(
                "Write this research report to the active directory?", default=False
            )
        if should_write:
            path = _write_research_report(result, out=out)
            console.print(f"[green]✓ Wrote research report:[/green] {path}")
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("update", rich_help_panel="Setup & Configuration")
def update_cmd(run: bool = typer.Option(False, "--run", help="Run the detected update command.")):
    """Show or run the recommended MagAgent update command."""
    from magent.install import update_plan

    plan = update_plan()
    if not run:
        console.print_json(data=plan)
        console.print(f"[dim]Run with `magent update --run` to execute:[/dim] {plan['command']}")
        return
    from magent.command_policy import run_policy_checked_exec

    console.print(f"[dim]Running:[/dim] {plan['command']}")
    completed = run_policy_checked_exec(plan["command"], cwd=".")
    if completed.returncode:
        raise typer.Exit(completed.returncode)


def _write_research_report(result: dict, *, out: str | None = None) -> Path:
    path = (
        Path(out).expanduser()
        if out
        else Path.cwd() / f"{_slugify_filename(str(result.get('topic') or 'research'))}.md"
    )
    path = path.resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_research_report_markdown(result), encoding="utf-8")
    return path


def _research_report_markdown(result: dict) -> str:
    lines = [f"# Research: {result.get('topic', 'Untitled')}", ""]
    questions = result.get("questions") or []
    if questions:
        lines.extend(["## Focus Questions", ""])
        lines.extend(f"- {question}" for question in questions)
        lines.append("")
    lines.extend(["## Summary", "", str(result.get("summary") or "No summary returned."), ""])
    sources = result.get("sources") or []
    if sources:
        lines.extend(["## Sources", ""])
        for index, source in enumerate(sources, start=1):
            lines.append(f"### {index}. {source.get('title') or source.get('url') or 'Untitled'}")
            lines.append("")
            lines.append(f"- URL: {source.get('url', '')}")
            if source.get("query"):
                lines.append(f"- Query: {source.get('query')}")
            if source.get("snippet"):
                lines.extend(["", str(source.get("snippet"))])
            if source.get("excerpt"):
                lines.extend(["", "Excerpt:", "", str(source.get("excerpt"))])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _slugify_filename(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return f"research-{slug or 'report'}"


def _one_shot_events(task: str, response: str, audit: dict, session) -> list[dict]:
    """Return coarse structured events for desktop timelines."""
    events = [{"type": "user_message", "content": task}]
    for command in session.scratchpad.get("commands_run", []):
        events.append({"type": "command", "command": command})
    for path in session.scratchpad.get("files_touched", []):
        events.append({"type": "file_touched", "path": path})
    for failure in session.scratchpad.get("permission_failures", []):
        events.append({"type": "permission_failure", "detail": failure})
    events.append({"type": "audit", "ok": bool(audit.get("ok", True)), "audit": audit})
    events.append({"type": "assistant_message", "content": response})
    return events


def _run_repl(username, config, main_provider, extract_provider, cwd, resume=None, profile=None):
    """Run the interactive REPL with streaming output."""
    from magent.agent import AgentSession
    from magent.execution_bridge import SessionTaskBridge
    from magent.tui import print_banner, print_streaming_response

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
        profile=profile,
    )
    if resume and resume.get("conversation"):
        # Restore the prior thread so the model has the context the user
        # remembers having.
        session.conversation.extend(resume["conversation"])
        session.turn_count = int(resume.get("turns") or 0)
    bridge = SessionTaskBridge(
        _store(),
        session,
        kind="interactive_session",
        title=f"Interactive session in {Path(cwd).name or cwd}",
        project=cwd,
        permission_policy=config.permission_mode,
        provider=main_provider,
        metadata={"source": "cli.interactive"},
    )
    session._ensure_messaging_started()
    session_name = session.messaging.name if session.messaging else "messaging-disabled"
    print_banner(
        username,
        main_provider.display_name,
        cwd,
        config.permission_mode,
        version=__version__,
        profile=profile.name if profile else "",
        session_name=session_name,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ended = False

    def _shutdown():
        nonlocal ended
        if ended:
            return
        console.print("\n[dim]Ending session...[/dim]")
        ended = True
        if loop.is_running():
            loop.create_task(session.end_session())
            return
        loop.run_until_complete(session.end_session())

    def _signal_handler(sig, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _signal_handler)

    console.print(
        "[dim]Type your message, [bold]/help[/bold] for commands, or "
        "[bold]exit[/bold] / [bold]quit[/bold] to end session.[/dim]"
    )
    console.print(
        "[dim]Use [bold]/compose[/bold] for formatted multiline prompts. "
        "Shift+Enter inserts a newline when your terminal supports it.[/dim]\n"
    )

    while True:
        try:
            user_input = read_user_prompt(username)
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue

        if user_input.strip().lower() in ("exit", "quit", "/exit", "/quit"):
            break

        if user_input.startswith("/"):
            if _handle_slash_command(user_input, session, config, main_provider, loop):
                continue
            console.print(
                f"[yellow]Unknown slash command:[/yellow] {user_input.split()[0]} "
                "[dim](try /help)[/dim]"
            )
            continue

        # Stream the agent response
        try:
            print_streaming_response(
                session.stream_chat(user_input),
                loop,
            )
        except KeyboardInterrupt:
            bridge.event("turn_interrupted", {"turn": session.turn_count})
            with contextlib.suppress(Exception):
                loop.run_until_complete(session.cancel_active_work())
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            bridge.event("turn_failed", {"turn": session.turn_count, "error": str(e)})
            console.print(f"[red]Error: {e}[/red]")

    try:
        console.print("\n[dim]Writing session memories...[/dim]")
        _shutdown()
        bridge.complete({"ok": True, "turns": session.turn_count})
        console.print("[dim green]Session ended. Goodbye![/dim green]")
    except BaseException as exc:
        bridge.fail(exc)
        raise
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _handle_slash_command(cmd: str, session, config, provider, loop=None) -> bool:
    """Handle slash commands. Returns True if handled."""
    import asyncio as _asyncio

    _loop = loop or _asyncio.get_event_loop()

    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        console.print(
            Panel(
                "[bold]Available commands:[/bold]\n\n"
                "  [cyan]/help[/cyan]            — Show this help\n"
                "  [cyan]/compose[/cyan]         — Write a formatted multiline prompt\n"
                "  [cyan]/goal <task>[/cyan]     — Start a verify/review goal loop prompt\n"
                "  [cyan]/jobs[/cyan]            — Show background jobs\n"
                "  [cyan]/tasks[/cyan]           — Show durable agent tasks\n"
                "  [cyan]/task <id> [action][/cyan] — Inspect, resume, retry, or cancel a task\n"
                "  [cyan]/context [q][/cyan]     — Audit active context and memory\n"
                "  [cyan]/config[/cyan]          — Show config control-center summary\n"
                "  [cyan]/statusline[/cyan]      — Preview statusline payload\n"
                "  [cyan]/usage[/cyan]           — Show token/tool/timing usage for this session\n"
                "  [cyan]/budget[/cyan]          — Show live session and daily spend guardrails\n"
                "  [cyan]/insights[/cyan]        — Show recent session diagnostics\n"
                "  [cyan]/session[/cyan]         — Show this session's durable identity\n"
                "  [cyan]/peers[/cyan]           — List other live local sessions\n"
                "  [cyan]/send <peer> <text>[/cyan] — Send a local coordination message\n"
                "  [cyan]/inbox [held][/cyan]    — Inspect accepted or held peer messages\n"
                "  [cyan]/accept <id>[/cyan]     — Accept a held peer message\n"
                "  [cyan]/refuse <id>[/cyan]     — Refuse a held peer message\n"
                "  [cyan]/receipts[/cyan]        — Show this session's delivery receipts\n"
                "  [cyan]/memory[/cyan]          — Show memory stats\n"
                "  [cyan]/why <query>[/cyan]     — Explain recalled memory and backlinks\n"
                "  [cyan]/skills[/cyan]          — List active skills\n"
                "  [cyan]/model[/cyan]           — Show current model\n"
                "  [cyan]/user[/cyan]            — Show current user\n"
                "  [cyan]/mode <mode>[/cyan]     — Set permission mode (silent/balanced/paranoid/yolo)\n"
                "  [cyan]/retry[/cyan]           — Retry the last user prompt\n"
                "  [cyan]/undo[/cyan]            — Remove the last exchange from context\n"
                "  [cyan]/spawn <task>[/cyan]    — Spawn a sub-agent for a focused task\n"
                "  [cyan]/clear[/cyan]           — Clear conversation history\n"
                "  [cyan]/exit[/cyan]            — End session",
                title="[bold cyan]MagAgent Help[/bold cyan]",
            )
        )
        return True

    if command == "/session":
        messaging = getattr(session, "messaging", None)
        if not messaging:
            console.print("[yellow]Local session messaging is disabled or unavailable.[/yellow]")
            return True
        console.print(
            Panel(
                f"[bold]Name:[/bold] {messaging.name}\n"
                f"[bold]Session ID:[/bold] {session.session_id}\n"
                f"[bold]Project:[/bold] {session.project_slug or ''}\n"
                f"[bold]Policy:[/bold] {messaging.policy}",
                title="Local Session Identity",
            )
        )
        return True

    if command == "/peers":
        session._ensure_messaging_started()
        messaging = getattr(session, "messaging", None)
        if not messaging:
            console.print("[yellow]Local session messaging is disabled or unavailable.[/yellow]")
            return True
        _print_session_peers(messaging.peers())
        return True

    if command == "/send":
        target_and_message = arg.split(maxsplit=1)
        if len(target_and_message) != 2:
            console.print("[yellow]Usage: /send <session-id-or-name> <message>[/yellow]")
            return True
        session._ensure_messaging_started()
        messaging = getattr(session, "messaging", None)
        if not messaging:
            console.print("[yellow]Local session messaging is disabled or unavailable.[/yellow]")
            return True
        target, message = target_and_message
        result = messaging.send(target, message)
        _print_session_receipt(result)
        return True

    if command == "/inbox":
        from magent.session_messaging import session_inbox

        held = arg.strip().lower() == "held"
        items = session_inbox(session.username, session.session_id, held=held)
        _print_session_inbox(items, held=held)
        return True

    if command in {"/accept", "/refuse"}:
        if not arg.strip():
            console.print(f"[yellow]Usage: {command} <message-id>[/yellow]")
            return True
        from magent.session_messaging import review_held_message

        decision = "accept" if command == "/accept" else "refuse"
        result = review_held_message(session.username, session.session_id, arg.strip(), decision)
        console.print_json(data=result)
        return True

    if command == "/receipts":
        from magent.session_messaging import session_receipts

        _print_session_receipts(session_receipts(session.username, session.session_id))
        return True

    if command == "/goal":
        if not arg:
            console.print("[yellow]Usage: /goal <measurable task>[/yellow]")
            return True
        from magent.daily_driver import build_goal_prompt
        from magent.tui import print_streaming_response

        print_streaming_response(session.stream_chat(build_goal_prompt(arg)), _loop)
        return True

    if command == "/jobs":
        from magent.daily_driver import jobs_summary

        _print_jobs_summary(jobs_summary(_store()))
        return True

    if command == "/tasks":
        from magent.task_runtime import TaskRuntime

        tasks = TaskRuntime(_store()).list_tasks(limit=20)
        table = Table("ID", "State", "Kind", "Task", "Updated")
        for item in tasks:
            table.add_row(
                item["id"],
                item["state"],
                item["kind"],
                str(item["title"])[:60],
                str(item.get("updated_at") or "")[:19],
            )
        console.print(table if tasks else "[dim]No durable tasks yet.[/dim]")
        return True

    if command == "/task":
        task_parts = arg.split()
        if not task_parts:
            console.print("[yellow]Usage: /task <id> [resume|retry|cancel][/yellow]")
            return True
        from magent.task_runtime import TaskRuntime, TaskRuntimeError

        runtime = TaskRuntime(_store())
        task_id = task_parts[0]
        action = task_parts[1].lower() if len(task_parts) > 1 else "show"
        try:
            if action == "show":
                item = runtime.get(task_id)
            elif action in {"resume", "retry", "cancel"}:
                item = getattr(runtime, action)(
                    task_id, reason=f"{action.title()} from interactive session"
                )
            else:
                console.print("[yellow]Action must be show, resume, retry, or cancel.[/yellow]")
                return True
        except TaskRuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            return True
        if item is None:
            console.print(f"[red]Task not found: {task_id}[/red]")
        else:
            console.print_json(data={"ok": True, "task": item})
        return True

    if command == "/context":
        from magent.context import context_map
        from magent.daily_driver import context_audit

        data = context_map(_store(), project=os.getcwd(), memory_manager=session.memory, query=arg)
        _print_context_map(data)
        audit = context_audit(data)
        console.print("[bold]Suggestions[/bold]")
        for item in audit.get("suggestions", []):
            console.print(f"- {item}")
        return True

    if command == "/config":
        _print_config_center(config, provider.display_name)
        return True

    if command == "/statusline":
        from magent.daily_driver import render_statusline, statusline_data

        data = statusline_data(
            config, username=get_current_user() or "user", cwd=os.getcwd(), store=_store()
        )
        console.print(render_statusline(data))
        return True

    if command == "/usage":
        from magent.session_controls import session_usage

        _print_session_usage(session_usage(session.logger.path))
        return True

    if command == "/budget":
        status = session._spend.check()
        data = status.as_dict()
        data["enabled"] = session._spend.enabled
        console.print_json(data=data)
        return True

    if command == "/insights":
        from magent.session_controls import recent_insights

        _print_recent_insights(recent_insights())
        return True

    if command == "/compose":
        prompt = read_multiline_prompt(get_current_user() or "user")
        if prompt.strip():
            from magent.tui import print_streaming_response

            print_streaming_response(session.stream_chat(prompt), _loop)
        return True

    if command == "/memory":
        stats = session.memory.stats()
        _print_memory_stats(stats, get_current_user() or "?")
        return True

    if command == "/why":
        if not arg.strip():
            console.print("[yellow]Usage: /why <memory query>[/yellow]")
            return True
        results = session.memory.search(arg, max_results=5, mode="hybrid")
        table = Table("Memory", "Why recalled", "Backlinks", "Source")
        for item in results:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            table.add_row(
                str(item.get("id") or ""),
                str(item.get("reason") or item.get("reasons") or "graph match"),
                ", ".join(str(link) for link in item.get("backlinks", [])) or "none",
                str(
                    item.get("source")
                    or item.get("path")
                    or metadata.get("source")
                    or "local graph"
                ),
            )
        console.print(table if results else "[dim]No memory matched that query.[/dim]")
        return True

    if command == "/skills":
        skills = session.skill_registry.list_all()
        if not skills:
            console.print("[dim]No skills loaded.[/dim]")
        else:
            t = Table("Name", "Version", "Description")
            for s in skills:
                t.add_row(s["name"], s["version"], s["description"])
            console.print(t)
        return True

    if command == "/model":
        console.print(f"[bold]Provider:[/bold] {provider.display_name}")
        return True

    if command == "/user":
        console.print(f"[bold]User:[/bold] {get_current_user()}")
        return True

    if command == "/mode":
        from magent.permissions import PERMISSION_MODES

        modes = tuple(sorted(PERMISSION_MODES))
        if arg in modes:
            # Persisted, like `magent mode`. This used to change the in-memory
            # profile only, so the setting vanished with the session.
            session.config.set_permission_mode(arg)
            session.tools.permission_mode = arg
            console.print(f"[green]Permission mode set to [bold]{arg}[/bold][/green]")
        else:
            console.print(f"[yellow]Current mode: {config.permission_mode}[/yellow]")
            console.print(f"[dim]Available: {', '.join(modes)}[/dim]")
        return True

    if command == "/undo":
        from magent.session_controls import pop_last_turn

        removed = pop_last_turn(session.conversation)
        if removed.get("user") or removed.get("assistant"):
            console.print("[green]Removed the last exchange from conversation context.[/green]")
            if removed.get("user"):
                console.print(f"[dim]Last prompt:[/dim] {removed['user'][:180]}")
        else:
            console.print("[dim]Nothing to undo.[/dim]")
        return True

    if command == "/retry":
        from magent.session_controls import last_user_message, pop_last_turn
        from magent.tui import print_streaming_response

        last = last_user_message(session.conversation)
        if not last:
            console.print("[yellow]No previous prompt to retry.[/yellow]")
            return True
        pop_last_turn(session.conversation)
        console.print(f"[dim]Retrying:[/dim] {last[:180]}")
        print_streaming_response(session.stream_chat(last), _loop)
        return True

    if command == "/spawn":
        if not arg:
            console.print("[yellow]Usage: /spawn [@profile] <task description>[/yellow]")
            return True
        import uuid as _uuid

        task_id = f"sub_{_uuid.uuid4().hex[:6]}"
        profile_name = ""
        description = arg
        if arg.startswith("@"):
            profile_name, _, description = arg[1:].partition(" ")
            if not description.strip():
                console.print("[yellow]Provide a task after the subagent profile.[/yellow]")
                return True
        console.print(f"[dim]Spawning sub-agent [{task_id}]...[/dim]")
        result = _loop.run_until_complete(
            session.spawn_subagent(task_id, description.strip(), profile_name=profile_name.strip())
        )
        from magent.tui import print_response

        console.print(f"[dim cyan]Sub-agent [{task_id}] result:[/dim cyan]")
        print_response(result)
        return True

    if command == "/clear":
        session.conversation.clear()
        session.turn_count = 0
        console.print("[dim]Conversation history cleared.[/dim]")
        return True

    if command == "/db":
        from magent.tools.db import list_databases

        username = get_current_user() or "default"
        result = list_databases(username)
        dbs = result.get("databases", [])
        if not dbs:
            console.print("[dim]No databases yet. Use db_execute to create tables.[/dim]")
        else:
            t = Table("Database", "Size")
            from magent.utils import human_bytes

            for d in dbs:
                t.add_row(d["name"], human_bytes(d["size_bytes"]))
            console.print(t)
        return True

    return False


# ─────────────────────────────────────────────
# Workbench subcommands
# ─────────────────────────────────────────────


@task_app.command("add")
def task_add_cmd(
    title: str = typer.Argument(...),
    project: str = typer.Option("", "--project", "-p"),
    priority: str = typer.Option("normal", "--priority"),
):
    """Add a task to the persistent local task ledger."""
    from magent.workbench import task_add

    item = task_add(_store(), title, project, priority)
    console.print(f"[green]✓ Added {item['id']}[/green] {item['title']}")


@task_app.command("list")
def task_list_cmd(
    status: str | None = typer.Option(None, "--status"),
    project: str | None = typer.Option(None, "--project", "-p"),
):
    """List tasks."""
    from magent.workbench import task_list

    tasks = task_list(_store(), status, project)
    table = Table("ID", "Status", "Priority", "Project", "Title")
    for task in tasks:
        table.add_row(
            task["id"],
            task.get("status", "?"),
            task.get("priority", ""),
            task.get("project", ""),
            task.get("title", ""),
        )
    console.print(table)


@task_app.command("done")
def task_done_cmd(task_id: str = typer.Argument(...)):
    """Mark a task done."""
    from magent.workbench import now_iso

    item = _store().update_item("tasks", task_id, status="done", completed_at=now_iso())
    if not item:
        console.print(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ Completed {task_id}[/green]")


@task_app.command("report")
def task_report_cmd():
    """Show task counts by status and project."""
    store = _store()
    tasks = store.read("tasks", [])
    by_status: dict[str, int] = {}
    by_project: dict[str, int] = {}
    for task in tasks:
        by_status[task.get("status", "?")] = by_status.get(task.get("status", "?"), 0) + 1
        project = task.get("project") or "(none)"
        by_project[project] = by_project.get(project, 0) + 1
    console.print(Panel(f"By status: {by_status}\nBy project: {by_project}", title="Task Ledger"))


@artifact_app.command("add")
def artifact_add_cmd(
    path: str = typer.Argument(...),
    kind: str = typer.Option("", "--kind", "-k"),
    title: str = typer.Option("", "--title", "-t"),
):
    """Track a generated artifact."""
    from magent.workbench import artifact_add

    item = artifact_add(_store(), path, kind, title)
    console.print(f"[green]✓ Tracked {item['id']}[/green] {item['path']}")


@artifact_app.command("list")
def artifact_list_cmd():
    """List tracked artifacts."""
    table = Table("ID", "Kind", "Exists", "Title", "Path")
    for item in _store().read("artifacts", []):
        table.add_row(
            item["id"],
            item.get("kind", ""),
            "yes" if item.get("exists") else "no",
            item.get("title", ""),
            item.get("path", ""),
        )
    console.print(table)


@artifact_app.command("show")
def artifact_show_cmd(artifact_id: str = typer.Argument(...)):
    """Show artifact metadata."""
    from magent.workbench import artifact_show

    item = artifact_show(_store(), artifact_id)
    if not item:
        console.print(f"[red]Artifact not found: {artifact_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@artifact_app.command("checksum")
def artifact_checksum_cmd(artifact_id: str = typer.Argument(...)):
    """Calculate and store an artifact checksum."""
    from magent.workbench import artifact_checksum

    console.print_json(data=artifact_checksum(_store(), artifact_id))


@artifact_app.command("open")
def artifact_open_cmd(artifact_id: str = typer.Argument(...)):
    """Show the local path for an artifact."""
    from magent.workbench import artifact_open_info

    console.print_json(data=artifact_open_info(_store(), artifact_id))


@knowledge_app.command("remember")
def knowledge_remember_cmd(
    text: str = typer.Argument(...),
    tags: Annotated[list[str] | None, typer.Option("--tag", "-t")] = None,
):
    """Remember a personal knowledge note."""
    from magent.workbench import remember

    item = remember(_store(), text, tags or [])
    console.print(f"[green]✓ Remembered {item['id']}[/green]")


@knowledge_app.command("recall")
def knowledge_recall_cmd(query: str = typer.Argument(...)):
    """Recall personal knowledge notes."""
    from magent.workbench import recall

    table = Table("ID", "Tags", "Text")
    for item in recall(_store(), query):
        table.add_row(item["id"], ", ".join(item.get("tags", [])), item.get("text", "")[:100])
    console.print(table)


@knowledge_app.command("forget")
def knowledge_forget_cmd(item_id: str = typer.Argument(...)):
    """Forget a personal knowledge note."""
    store = _store()
    items = [item for item in store.read("knowledge", []) if item.get("id") != item_id]
    store.write("knowledge", items)
    console.print(f"[green]✓ Forgotten {item_id}[/green]")


@project_app.command("profile")
def project_profile_cmd(path: str = typer.Option(".", "--path", "-p")):
    """Create or refresh a project profile."""
    from magent.workbench import save_project_profile

    profile = save_project_profile(_store(), path)
    console.print(Panel(str(profile), title="Project Profile"))


@project_app.command("list")
def project_list_cmd():
    """List saved project profiles."""
    table = Table("Name", "Root", "Commands")
    for item in _store().read("projects", []):
        table.add_row(
            item.get("name", ""), item.get("root", ""), ", ".join(item.get("commands", []))
        )
    console.print(table)


@project_app.command("commands")
def project_commands_cmd(path: str = typer.Option(".", "--path", "-p")):
    """Show discovered project test/lint/build commands."""
    from magent.workbench import infer_project_commands

    for command in infer_project_commands(Path(path).resolve()):
        console.print(command)


@project_app.command("roles")
def project_roles_cmd(path: str = typer.Option(".", "--path", "-p")):
    """Show project command roles."""
    from magent.workbench import project_command_roles

    console.print_json(data=project_command_roles(path))


@project_app.command("doctor")
def project_doctor_cmd(path: str = typer.Option(".", "--path", "-p")):
    """Report missing/broken project command roles."""
    from magent.workbench import project_doctor

    console.print_json(data=project_doctor(path, _store()))


@project_app.command("playbook")
def project_playbook_cmd(
    path: str = typer.Option(".", "--path", "-p"),
    init: bool = typer.Option(False, "--init", help="Create a starter .magent/playbook.toml"),
):
    """Show or initialize the project playbook."""
    from magent.playbook import playbook_path, playbook_summary, playbook_template

    target = playbook_path(path)
    if init:
        if target.exists():
            console.print_json(data={"ok": False, "error": f"Playbook already exists: {target}"})
            raise typer.Exit(1)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(playbook_template(), encoding="utf-8")
    console.print_json(data=playbook_summary(path))


@project_app.command("init")
def project_init_cmd(
    path: str = typer.Option(".", "--path", "-p"),
    force: bool = typer.Option(False, "--force"),
):
    """Create CLI-friendly MagAgent project config and playbook files."""
    from magent.ux_flows import init_project

    console.print_json(data=init_project(path, force=force))


@project_app.command("wizard")
def project_wizard_cmd(
    path: str = typer.Option(".", "--path", "-p"),
    force: bool = typer.Option(False, "--force"),
):
    """Explain and create project config and playbook files."""
    # Call the underlying helper, not the Typer command: invoking a command as
    # a function leaves every unpassed parameter as a truthy OptionInfo.
    from magent.ux_flows import init_project

    console.print(
        Panel(
            "Creates .magent/config.toml and .magent/playbook.toml for project-specific defaults, "
            "test/build commands, review rules, and reusable routines. Existing files are preserved "
            "unless --force is supplied.",
            title="Project Bootstrap",
        )
    )
    console.print_json(data=init_project(path, force=force))


@project_app.command("config")
def project_config_cmd(path: str = typer.Option(".", "--path", "-p")):
    """Show project-local .magent/config.toml values."""
    from magent.workbench import load_project_config

    console.print_json(data=load_project_config(path))


@project_app.command("command-history")
def project_command_history_cmd(path: str = typer.Option(".", "--path", "-p")):
    """Show learned command outcomes for a project."""
    from magent.workbench import command_history

    table = Table("Time", "OK", "Source", "Command")
    for item in command_history(_store(), path):
        table.add_row(
            item.get("created_at", "")[:19],
            "yes" if item.get("ok") else "no",
            item.get("source", ""),
            item.get("command", ""),
        )
    console.print(table)


@project_app.command("command-promote")
def project_command_promote_cmd(
    command: str = typer.Argument(...),
    path: str = typer.Option(".", "--path", "-p"),
):
    """Promote a command into the saved project profile."""
    from magent.workbench import promote_command

    console.print_json(data=promote_command(_store(), path, command))


@inbox_app.command("add")
def inbox_add_cmd(text: str = typer.Argument(...), source: str = typer.Option("cli", "--source")):
    """Add an item to the local inbox."""
    item = _store().append("inbox", {"text": text, "source": source, "status": "new"})
    console.print(f"[green]✓ Added {item['id']}[/green]")


@inbox_app.command("list")
def inbox_list_cmd(status: str | None = typer.Option(None, "--status")):
    """List inbox items."""
    items = _store().read("inbox", [])
    if status:
        items = [item for item in items if item.get("status") == status]
    table = Table("ID", "Status", "Source", "Text")
    for item in items:
        table.add_row(
            item["id"], item.get("status", ""), item.get("source", ""), item.get("text", "")[:100]
        )
    console.print(table)


@inbox_app.command("triage")
def inbox_triage_cmd():
    """Group inbox items into tasks and notes using simple heuristics."""
    store = _store()
    from magent.workbench import task_add

    count = 0
    items = store.read("inbox", [])
    for item in items:
        if item.get("status") != "new":
            continue
        if any(word in item.get("text", "").lower() for word in ("fix", "todo", "task", "build")):
            task_add(store, item["text"])
        item["status"] = "triaged"
        count += 1
    store.write("inbox", items)
    console.print(f"[green]✓ Triaged {count} inbox items[/green]")


@routine_app.command("add")
def routine_add_cmd(
    name: str = typer.Argument(...),
    prompt: str = typer.Argument(...),
    schedule: str = typer.Option("", "--schedule"),
):
    """Register a recurring routine prompt."""
    item = _store().append("routines", {"name": name, "prompt": prompt, "schedule": schedule})
    console.print(f"[green]✓ Added routine {item['id']}[/green]")


@routine_app.command("list")
def routine_list_cmd():
    """List routines."""
    table = Table("ID", "Name", "Schedule", "Prompt")
    for item in _store().read("routines", []):
        table.add_row(
            item["id"], item.get("name", ""), item.get("schedule", ""), item.get("prompt", "")[:80]
        )
    console.print(table)


@routine_app.command("run")
def routine_run_cmd(name_or_id: str = typer.Argument(...)):
    """Print the prompt for a routine so it can be run as a one-shot task."""
    for item in _store().read("routines", []):
        if item.get("id") == name_or_id or item.get("name") == name_or_id:
            console.print(item.get("prompt", ""))
            return
    console.print(f"[red]Routine not found: {name_or_id}[/red]")
    raise typer.Exit(1)


@followup_app.command("add")
def followup_add_cmd(text: str = typer.Argument(...), when: str = typer.Option("", "--when")):
    """Add a follow-up reminder entry."""
    item = _store().append("followups", {"text": text, "when": when, "status": "open"})
    console.print(f"[green]✓ Added {item['id']}[/green]")


@followup_app.command("list")
def followup_list_cmd():
    """List follow-ups."""
    table = Table("ID", "When", "Status", "Text")
    for item in _store().read("followups", []):
        table.add_row(
            item["id"], item.get("when", ""), item.get("status", ""), item.get("text", "")[:100]
        )
    console.print(table)


def _build_and_save_plan(
    goal: str,
    project: str,
    *,
    save: bool = False,
    executable: bool = False,
    commands: list[str] | None = None,
    include_diff: bool = True,
) -> tuple[str, dict | None]:
    """Plain-Python core of `magent plan`.

    Typer commands must never be called as functions: the parameters keep their
    `typer.OptionInfo` defaults, every `if option:` branch fires because those
    objects are truthy, and the values are then used as data. `magent run` did
    exactly that and died with "OptionInfo object is not iterable" after
    already appending a runs record.
    """
    from magent.workbench import build_plan, save_execution_plan, save_plan

    text = build_plan(project, goal)
    item = None
    if save:
        if executable:
            item = save_execution_plan(
                _store(),
                project,
                goal,
                commands=commands or [],
                include_diff=include_diff,
            )
        else:
            item = save_plan(_store(), project, goal)
    return text, item


@app.command("plan", rich_help_panel="Planning, Review & Release")
def plan_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    save: bool = typer.Option(False, "--save", help="Save the plan in the local workbench"),
    executable: bool = typer.Option(
        False,
        "--executable",
        help="When saving, create an executable plan compatible with plan-preview/apply.",
    ),
    command: Annotated[list[str] | None, typer.Option("--command", "-c")] = None,
    no_diff: bool = typer.Option(
        False, "--no-diff", help="Do not capture the current diff for executable plans."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable plan data."),
):
    """Generate a local plan without modifying files."""
    text, item = _build_and_save_plan(
        goal,
        project,
        save=save,
        executable=executable,
        commands=command or [],
        include_diff=not no_diff,
    )
    if json_output:
        console.print_json(data={"ok": True, "plan_markdown": text, "saved": item})
        return
    console.print(text)
    if item:
        mode = item.get("mode") or "draft"
        console.print(f"\n[green]✓ Saved {mode} plan {item['id']}[/green]")
        console.print("[dim]Next commands:[/dim]")
        console.print(f"  magent plan-show {item['id']}")
        if executable:
            console.print(f"  magent plan-preview {item['id']}")
            console.print(f"  magent plan-apply {item['id']} --dry-run")
        else:
            console.print(f"  magent plan-apply {item['id']} --dry-run")


@app.command("plan-list", rich_help_panel="Planning, Review & Release")
def plan_list_cmd(status: str | None = typer.Option(None, "--status")):
    """List saved plans."""
    from magent.workbench import list_plans

    table = Table("ID", "Status", "Project", "Goal")
    for item in list_plans(_store(), status=status):
        table.add_row(
            item["id"], item.get("status", ""), item.get("project", ""), item.get("goal", "")[:90]
        )
    console.print(table)


@app.command("plan-apply", rich_help_panel="Planning, Review & Release")
def plan_apply_cmd(
    plan_id: str = typer.Argument(...),
    run_checks: bool = typer.Option(False, "--run-checks"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    sandbox: str | None = typer.Option(
        None, "--sandbox", help="Run in worktree, copy, or container sandbox"
    ),
    keep_sandbox: bool = typer.Option(False, "--keep-sandbox"),
    image: str = typer.Option(
        "python:3.12", "--image", help="Container image for --sandbox container"
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Mark a saved plan applied, optionally running its suggested checks."""
    from magent.workbench import apply_plan

    if sandbox:
        from magent.sandbox import execute_plan_sandbox, sandbox_plan_preview

        if dry_run:
            console.print_json(data=sandbox_plan_preview(_store(), plan_id, mode=sandbox))
            return
        if not yes:
            confirm = Prompt.ask(
                f"Run plan '{plan_id}' in {sandbox} sandbox?", choices=["y", "n"], default="n"
            )
            if confirm != "y":
                raise typer.Exit()
        console.print_json(
            data=execute_plan_sandbox(
                _store(),
                plan_id,
                mode=sandbox,
                run_checks=run_checks,
                keep=keep_sandbox,
                image=image,
            )
        )
        return
    if not dry_run and not yes:
        confirm = Prompt.ask(f"Apply plan '{plan_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=apply_plan(_store(), plan_id, run_checks=run_checks, dry_run=dry_run))


@app.command("plan-sandbox", rich_help_panel="Planning, Review & Release")
def plan_sandbox_cmd(
    plan_id: str = typer.Argument(...),
    mode: str = typer.Option("worktree", "--mode"),
    run_checks: bool = typer.Option(False, "--run-checks"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    keep: bool = typer.Option(False, "--keep"),
    image: str = typer.Option("python:3.12", "--image"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Run or preview a saved plan in an isolated sandbox."""
    from magent.cli.command_context import confirm_or_exit
    from magent.sandbox import execute_plan_sandbox, sandbox_plan_preview

    if dry_run:
        console.print_json(data=sandbox_plan_preview(_store(), plan_id, mode=mode))
        return

    # `plan-apply --sandbox` asks before running plan operations; this ran the
    # very same operations without asking.
    confirm_or_exit(
        f"Run plan {plan_id} in a {mode} sandbox (executes its commands)?",
        assume_yes=yes,
    )
    console.print_json(
        data=execute_plan_sandbox(
            _store(), plan_id, mode=mode, run_checks=run_checks, keep=keep, image=image
        )
    )


@app.command("plan-exec", rich_help_panel="Planning, Review & Release")
def plan_exec_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    command: Annotated[list[str] | None, typer.Option("--command", "-c")] = None,
    no_diff: bool = typer.Option(False, "--no-diff"),
):
    """Create an executable plan from current diff and optional shell commands."""
    from magent.workbench import save_execution_plan

    item = save_execution_plan(
        _store(),
        project,
        goal,
        commands=command or [],
        include_diff=not no_diff,
    )
    console.print(f"[green]✓ Saved executable plan {item['id']}[/green]")
    console.print(item.get("preview", ""))


@app.command("plan-preview", rich_help_panel="Planning, Review & Release")
def plan_preview_cmd(plan_id: str = typer.Argument(...)):
    """Preview executable operations for a saved plan."""
    from magent.workbench import preview_plan, show_plan

    item = show_plan(_store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print(item.get("preview") or preview_plan(item))


@app.command("plan-run", rich_help_panel="Planning, Review & Release")
def plan_run_cmd(
    goal: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Create a pending plan-run record with checks, review, and diff context."""
    from magent.workbench import save_plan_run

    item = save_plan_run(_store(), project, goal)
    console.print(f"[green]✓ Saved pending plan {item['id']}[/green]")
    console.print(item.get("plan_markdown", ""))


@app.command("plan-show", rich_help_panel="Planning, Review & Release")
def plan_show_cmd(plan_id: str = typer.Argument(...)):
    """Show a saved plan record."""
    from magent.workbench import show_plan

    item = show_plan(_store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@app.command("plan-discard", rich_help_panel="Planning, Review & Release")
def plan_discard_cmd(
    plan_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")
):
    """Discard a saved plan."""
    from magent.workbench import discard_plan

    if not yes:
        confirm = Prompt.ask(f"Discard plan '{plan_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=discard_plan(_store(), plan_id))


@app.command("run", rich_help_panel="Everyday Agent Work")
def run_cmd(
    goal: str = typer.Argument(...),
    budget: str = typer.Option("", "--budget", help="Human budget note, e.g. 30m"),
    project: str | None = typer.Option(None, "--project"),
):
    """Record and print an autonomous work-session plan."""
    store = _store()
    item = store.append("runs", {"goal": goal, "budget": budget, "status": "planned"})
    console.print(f"[green]✓ Planned run {item['id']}[/green]")
    text, _saved = _build_and_save_plan(goal, project or os.getcwd())
    console.print(text)


@app.command("goal", rich_help_panel="Everyday Agent Work")
def goal_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    background: bool = typer.Option(
        False, "--background/--no-background", help="Queue the goal as a daemon task."
    ),
    run: bool = typer.Option(
        False, "--run/--no-run", help="Run the generated goal prompt immediately."
    ),
    verify: bool = typer.Option(
        True, "--verify/--no-verify", help="Include verifier pass instructions."
    ),
    review: bool = typer.Option(
        True, "--review/--no-review", help="Include reviewer pass instructions."
    ),
    max_loops: int = typer.Option(3, "--max-loops", min=1, max=20),
    verifier_model: str = typer.Option("cheap", "--verifier-model-role"),
    reviewer_model: str = typer.Option("review", "--reviewer-model-role"),
    orchestrated: bool = typer.Option(
        False,
        "--orchestrated/--no-orchestrated",
        help="Use staged cached-plan/sub-agent orchestration.",
    ),
    orchestrated_steps: int = typer.Option(
        3, "--orchestrated-steps", min=1, max=8, help="Maximum staged sub-agent steps."
    ),
    planning_model_role: str = typer.Option(
        "review", "--planning-model-role", help="Model role used for master/step planning metadata."
    ),
    execution_model_role: str = typer.Option(
        "coding", "--execution-model-role", help="Model role used for sub-agent execution metadata."
    ),
    provider: str | None = typer.Option(None, "--provider", help="Provider ID when using --run."),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name when using --run."),
    agent: str = typer.Option("", "--agent", help="Run this goal with a named OAP profile."),
    permission_mode: str | None = typer.Option(
        None, "--permission-mode", help="Permission mode when using --run."
    ),
    repair_attempts: int = typer.Option(
        2, "--repair-attempts", min=0, max=5, help="Audit repair attempts when using --run."
    ),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create a goal loop with verifier/reviewer workflow scaffolding."""
    if orchestrated:
        from magent.goal_orchestrator import create_orchestrated_goal, run_orchestrated_goal

        if run:
            if background:
                console.print(
                    "[red]Use either --run or --background for orchestrated goals, not both.[/red]"
                )
                raise typer.Exit(2)
            username = _require_user()
            cfg = load_config(username)
            if provider is None and model is None:
                try:
                    main_provider = build_provider_for_role(cfg, execution_model_role)
                except ProviderCredentialError as exc:
                    console.print(f"[red]Execution model role not ready:[/red] {exc}")
                    raise typer.Exit(1) from exc
            else:
                main_provider = _build_provider(cfg, provider, model)
            extract_provider = _build_extraction_provider(cfg)

            async def _run_orchestrated():
                return await run_orchestrated_goal(
                    _store(),
                    goal,
                    project=project,
                    username=username,
                    provider=main_provider,
                    extraction_provider=extract_provider,
                    config=cfg,
                    verify=verify,
                    review=review,
                    max_steps=orchestrated_steps,
                    planning_model_role=planning_model_role,
                    execution_model_role=execution_model_role,
                    agent_profile=agent,
                    quiet=json_output,
                )

            result = asyncio.run(_run_orchestrated())
        else:
            result = create_orchestrated_goal(
                _store(),
                goal,
                project=project,
                verify=verify,
                review=review,
                max_steps=orchestrated_steps,
                planning_model_role=planning_model_role,
                execution_model_role=execution_model_role,
                agent_profile=agent,
            )
            if background:
                from magent.daemon import enqueue_task

                queued = enqueue_task(
                    _store(),
                    "orchestrated_goal",
                    {"id": result["plan"]["id"], "goal": goal, "agent": agent},
                    project=project,
                )
                result["queued"] = queued
                result["goal"] = (
                    _store().update_item("goals", result["goal"]["id"], status="queued")
                    or result["goal"]
                )
                result["plan"] = (
                    _store().update_item(
                        "plans",
                        result["plan"]["id"],
                        status="queued",
                        orchestration={**result["orchestration"], "status": "queued"},
                    )
                    or result["plan"]
                )
                result["orchestration"] = result["plan"]["orchestration"]
        if json_output:
            console.print_json(data=result)
            return
        goal_item = result["goal"]
        plan = result["plan"]
        orchestration = result["orchestration"]
        console.print(f"[green]✓ Created orchestrated goal {goal_item['id']}[/green]")
        console.print(Panel(plan["plan_markdown"], title="Cached Master Plan"))
        console.print(f"[dim]Saved staged plan:[/dim] {plan['id']}")
        console.print(f"[dim]Cache key:[/dim] {orchestration['cache_key']}")
        if result.get("queued"):
            console.print(f"[dim]Queued background job:[/dim] {result['queued']['id']}")
            console.print(
                "[dim]Inspect with `magent jobs` and run due work with `magent daemon run-once`.[/dim]"
            )
        else:
            console.print("[dim]Preview or run staged execution with:[/dim]")
            console.print(f"  magent goal-run {plan['id']} --dry-run")
            console.print(f"  magent goal-run {plan['id']}")
        return

    from magent.daily_driver import create_goal

    result = create_goal(
        _store(),
        goal,
        project=project,
        verify=verify,
        review=review,
        background=background,
        max_loops=max_loops,
        verifier_model=verifier_model,
        reviewer_model=reviewer_model,
        agent_profile=agent,
    )
    if json_output:
        console.print_json(data=result)
        return
    goal_item = result["goal"]
    plan = result["plan"]
    console.print(f"[green]✓ Created goal {goal_item['id']}[/green]")
    console.print(Panel(goal_item["prompt"], title="Goal Loop Prompt"))
    console.print(f"[dim]Saved plan:[/dim] {plan['id']}")
    if result.get("queued"):
        console.print(f"[dim]Queued background job:[/dim] {result['queued']['id']}")
        console.print(
            "[dim]Inspect with `magent jobs` and run due work with `magent daemon run-once`.[/dim]"
        )
    elif run:
        username = _require_user()
        cfg = load_config(username)
        main_provider = _build_provider(cfg, provider, model)
        extract_provider = _build_extraction_provider(cfg)
        effective_profile = _resolve_cli_profile(agent or None, project, cfg)
        if effective_profile is not None and provider is None and model is None:
            main_provider = _build_provider(
                cfg, effective_profile.provider, effective_profile.model
            )
        _run_one_shot(
            username,
            cfg,
            main_provider,
            extract_provider,
            str(Path(project).resolve()),
            goal_item["prompt"],
            permission_mode_override=permission_mode,
            repair_attempts=repair_attempts,
            strict_audit=True,
            profile=effective_profile,
        )
    else:
        console.print("[dim]Run now with:[/dim]")
        console.print(
            f"  magent goal {json.dumps(goal)} --project {json.dumps(str(Path(project).resolve()))} --run"
        )
        console.print("[dim]Or run the generated prompt directly:[/dim]")
        console.print(
            f"  magent ask {json.dumps(goal_item['prompt'])} --project {json.dumps(str(Path(project).resolve()))} --repair-attempts 2 --strict-audit"
        )


@app.command("goal-run", rich_help_panel="Everyday Agent Work")
def goal_run_cmd(
    plan_id: str = typer.Argument(..., help="Saved orchestrated plan id"),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory fallback for provider execution."
    ),
    retry_step: int = typer.Option(
        0, "--retry-step", min=0, help="Rerun a specific 1-based step and following steps."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run/--run", help="Preview the next step packet without executing."
    ),
    provider: str | None = typer.Option(None, "--provider", help="Provider ID override."),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name override."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Resume, retry, or preview a saved orchestrated goal plan."""
    from magent.goal_orchestrator import preview_orchestrated_plan, run_orchestrated_plan

    store_obj = _store()
    try:
        preview = preview_orchestrated_plan(store_obj, plan_id, retry_step=retry_step)
    except ValueError as exc:
        preview = {"ok": False, "error": str(exc), "plan_id": plan_id}
    if not preview.get("ok"):
        if json_output:
            console.print_json(data=preview)
        else:
            console.print(f"[red]{preview.get('error')}[/red]")
        raise typer.Exit(1)
    if dry_run:
        if json_output:
            console.print_json(data=preview)
            return
        _print_orchestrated_preview(preview)
        return

    username = _require_user()
    cfg = load_config(username)
    execution_role = preview["orchestration"]["execution_model_role"]
    if provider is None and model is None:
        try:
            main_provider = build_provider_for_role(cfg, execution_role)
        except ProviderCredentialError as exc:
            console.print(f"[red]Execution model role not ready:[/red] {exc}")
            raise typer.Exit(1) from exc
    else:
        main_provider = _build_provider(cfg, provider, model)
    extract_provider = _build_extraction_provider(cfg)

    async def _run_saved_orchestrated():
        return await run_orchestrated_plan(
            store_obj,
            plan_id,
            username=username,
            provider=main_provider,
            extraction_provider=extract_provider,
            config=cfg,
            retry_step=retry_step,
            quiet=json_output,
        )

    result = asyncio.run(_run_saved_orchestrated())
    if json_output:
        console.print_json(data=result)
        return
    _print_orchestrated_run_result(result)
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("jobs", rich_help_panel="Everyday Agent Work")
def jobs_cmd(
    status: str = typer.Option("", "--status"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show background daemon jobs in a friendly table."""
    from magent.daily_driver import jobs_summary

    data = jobs_summary(_store(), status=status)
    if json_output:
        console.print_json(data=data)
        return
    _print_jobs_summary(data)


@app.command("resume", rich_help_panel="Everyday Agent Work")
def resume_cmd(
    session_id: str = typer.Argument("", help="Session id; omit for the most recent."),
    list_sessions: bool = typer.Option(False, "--list", "-l", help="List resumable sessions."),
    max_turns: int = typer.Option(40, "--max-turns", help="Most recent exchanges to restore."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Resume a previous conversation.

    Conversations used to live only in memory, so closing the terminal lost the
    thread even though every turn had been logged.
    """
    from magent.session_resume import list_resumable_sessions, load_session_transcript

    if list_sessions:
        sessions = list_resumable_sessions(user=get_current_user())
        if json_output:
            console.print_json(data={"ok": True, "sessions": sessions})
            return
        if not sessions:
            console.print("[dim]No resumable sessions yet.[/dim]")
            return
        table = Table("Session", "Started", "Turns", "Opening message")
        for item in sessions:
            table.add_row(
                item["session"][:26], str(item["started"])[:19], str(item["turns"]), item["preview"]
            )
        console.print(table)
        return

    result = load_session_transcript(session_id, max_turns=max_turns)
    if json_output:
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
        return

    if not result.get("ok"):
        console.print(f"[red]{result.get('error')}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Resuming session {result['session']}[/green] ({result['turns']} turns)")
    if result.get("lossy"):
        console.print(
            "[yellow]This session predates full transcripts; turns are restored from "
            "logged previews and may be truncated.[/yellow]"
        )
    if result.get("truncated"):
        console.print(f"[dim]Only the last {max_turns} exchanges were restored.[/dim]")

    username = _require_user()
    config = load_config(username)
    _run_repl(
        username,
        config,
        _build_provider(config, None, None),
        _build_extraction_provider(config),
        os.getcwd(),
        resume=result,
    )


@app.command("statusline", rich_help_panel="Setup & Configuration")
def statusline_cmd(
    template: str = typer.Option(
        "", "--template", "-t", help="Python format template for statusline fields."
    ),
    json_output: bool = typer.Option(False, "--json"),
):
    """Render a compact shell statusline payload."""
    from magent.daily_driver import render_statusline, statusline_data

    username = get_current_user() or "default"
    config = load_config(username)
    data = statusline_data(config, username=username, cwd=os.getcwd(), store=_store())
    if json_output:
        console.print_json(data=data)
        return
    console.print(render_statusline(data, template=template))


@app.command("review", rich_help_panel="Planning, Review & Release")
def review_cmd(
    base: str = typer.Option("HEAD", "--since"),
    project: str = typer.Option(".", "--project", "-p"),
    json_out: bool = typer.Option(False, "--json", help="Emit structured JSON"),
    save: bool = typer.Option(False, "--save", help="Save review findings to the workbench"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="Exit non-zero if findings at or above priority exist"
    ),
):
    """Review the local git diff for common risks."""
    from magent.workbench import review_diff, review_fails_threshold, review_summary, save_review

    if save:
        item = save_review(_store(), project, base)
        console.print(f"[green]✓ Saved review {item['id']}[/green]")
        if json_out:
            console.print_json(data=item)
        # --save used to return before this check, so `--save --fail-on P1`
        # always exited 0 no matter what the review found.
        if fail_on and review_fails_threshold(
            (item.get("summary") or {}).get("findings", []), fail_on
        ):
            raise typer.Exit(1)
        return
    if json_out:
        summary = review_summary(project, base)
        console.print_json(data=summary)
        if fail_on and review_fails_threshold(summary.get("findings", []), fail_on):
            raise typer.Exit(1)
        return
    findings = review_diff(project, base)
    if not findings:
        console.print("[green]No heuristic findings.[/green]")
        return
    table = Table("Priority", "Category", "Diff Line", "Finding", "Evidence")
    for finding in findings:
        table.add_row(
            finding["priority"],
            finding.get("category", "general"),
            str(finding["line"]),
            finding["message"],
            finding["evidence"],
        )
    console.print(table)
    if fail_on and review_fails_threshold(findings, fail_on):
        raise typer.Exit(1)


@app.command("review-show", rich_help_panel="Planning, Review & Release")
def review_show_cmd(review_id: str = typer.Argument(...)):
    """Show a saved review."""
    from magent.workbench import review_show

    item = review_show(_store(), review_id)
    if not item:
        console.print(f"[red]Review not found: {review_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@app.command("repo-graph", rich_help_panel="Code Intelligence & Testing")
def graph_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Show a lightweight repository import graph."""
    from magent.workbench import repo_graph

    console.print_json(data=repo_graph(project))


code_app.command("graph")(graph_cmd)


@app.command("test-intel", rich_help_panel="Code Intelligence & Testing")
def test_intel_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Suggest tests related to current git changes."""
    from magent.workbench import suggest_tests

    suggestions = suggest_tests(project)
    console.print("\n".join(suggestions) if suggestions else "[dim]No suggestions.[/dim]")


@code_app.command("index")
def code_index_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Build and save a code intelligence index."""
    from magent.workbench import save_code_index

    with console.status("[bold]Indexing code...[/bold]"):
        index = save_code_index(_store(), project)
    console.print_json(
        data={"root": index["root"], "files": len(index["files"]), "symbols": len(index["symbols"])}
    )


@code_app.command("symbols")
def code_symbols_cmd(
    query: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Search indexed code symbols."""
    from magent.workbench import search_symbols

    table = Table("Kind", "Name", "Path", "Line")
    for item in search_symbols(_store(), query, project):
        table.add_row(
            item.get("kind", ""),
            item.get("name", ""),
            item.get("path", ""),
            str(item.get("line", "")),
        )
    console.print(table)


@code_app.command("related")
def code_related_cmd(
    file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Show code and tests related to a file."""
    from magent.workbench import related_code

    console.print_json(data=related_code(_store(), project, file))


@test_app.command("map")
def test_map_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Build a source-to-test map."""
    from magent.workbench import test_map

    with console.status("[bold]Mapping tests...[/bold]"):
        result = test_map(project)
    console.print_json(data=result)


@test_app.command("related")
def test_related_cmd(
    file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Show tests related to a source file."""
    from magent.workbench import related_tests

    for test in related_tests(project, file):
        console.print(test)


@test_app.command("explain")
def test_explain_cmd(
    file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Explain why tests are related to a source file."""
    from magent.workbench import explain_related_tests

    console.print_json(data=explain_related_tests(project, file))


@test_app.command("run-related")
def test_run_related_cmd(
    file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Run tests related to a source file."""
    from magent.workbench import run_related_tests

    console.print_json(data=run_related_tests(project, file))


@patch_app.command("save")
def patch_save_cmd(
    name: str = typer.Option("", "--name"), project: str = typer.Option(".", "--project", "-p")
):
    """Save the current git diff to the patch queue."""
    from magent.workbench import save_patch

    item = save_patch(_store(), project, name)
    console.print(f"[green]✓ Saved {item['id']}[/green] {item['path']}")


@patch_app.command("list")
def patch_list_cmd():
    """List saved patches."""
    table = Table("ID", "Name", "Bytes", "Path")
    for item in _store().read("patches", []):
        table.add_row(
            item["id"], item.get("name", ""), str(item.get("bytes", 0)), item.get("path", "")
        )
    console.print(table)


@patch_app.command("preview")
def patch_preview_cmd(patch_id: str = typer.Argument(...)):
    """Preview a saved patch."""
    from magent.workbench import patch_preview

    console.print_json(data=patch_preview(_store(), patch_id))


@patch_app.command("explain")
def patch_explain_cmd(patch_id: str = typer.Argument(...)):
    """Explain saved patch impact."""
    from magent.workbench import patch_explain

    console.print_json(data=patch_explain(_store(), patch_id))


@patch_app.command("apply")
def patch_apply_cmd(
    patch_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")
):
    """Apply a saved patch after git apply --check passes."""
    from magent.workbench import apply_saved_patch

    if not yes:
        confirm = Prompt.ask(f"Apply patch '{patch_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=apply_saved_patch(_store(), patch_id))


@patch_app.command("revert")
def patch_revert_cmd(
    patch_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")
):
    """Reverse-apply a saved patch after git apply -R --check passes."""
    from magent.workbench import apply_saved_patch

    if not yes:
        confirm = Prompt.ask(f"Reverse patch '{patch_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=apply_saved_patch(_store(), patch_id, reverse=True))


@workspace_app.command("status")
def workspace_status_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Show git/workbench status for the workspace."""
    from magent.workbench import workspace_status

    console.print_json(data=workspace_status(_store(), project))


@workspace_app.command("clean-report")
def workspace_clean_report_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Show non-destructive cleanup suggestions."""
    from magent.workbench import workspace_clean_report

    console.print_json(data=workspace_clean_report(_store(), project))


@release_app.command("check")
def release_check_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Run release readiness checks."""
    from magent.workbench import release_check

    with console.status("[bold]Running release checks...[/bold]"):
        result = release_check(_store(), project)
    console.print_json(data=result)


@release_app.command("notes")
def release_notes_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    since: str = typer.Option("HEAD~5", "--since"),
):
    """Generate release notes from recent commits."""
    from magent.workbench import release_notes

    console.print_json(data=release_notes(project, since=since))


@release_app.command("evidence")
def release_evidence_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    eval_report: str = typer.Option("", "--eval-report"),
    memory_report: str = typer.Option("", "--memory-report"),
    performance_report: str = typer.Option("", "--performance-report"),
    supply_chain_report: str = typer.Option("", "--supply-chain-report"),
    coverage: float | None = typer.Option(None, "--coverage", min=0, max=100),
    coverage_required: float = typer.Option(70, "--coverage-required", min=0, max=100),
    tests: str = typer.Option(
        "", "--tests", help="Recorded test result, for example '724 passed'."
    ),
    ci_url: str = typer.Option("", "--ci-url"),
    artifact: Annotated[list[str] | None, typer.Option("--artifact")] = None,
    exception: Annotated[list[str] | None, typer.Option("--exception")] = None,
    out: str = typer.Option("", "--out", "-o"),
):
    """Create a machine-readable release qualification evidence bundle."""
    from magent.release_evidence import build_release_evidence, write_release_evidence

    report = build_release_evidence(
        project,
        eval_report=eval_report or None,
        memory_report=memory_report or None,
        performance_report=performance_report or None,
        supply_chain_report=supply_chain_report or None,
        coverage_percent=coverage,
        coverage_required=coverage_required,
        tests=tests,
        ci_url=ci_url,
        artifacts=artifact,
        exceptions=exception,
    )
    if out:
        report["report_path"] = write_release_evidence(report, out)
    console.print_json(data=report)
    raise typer.Exit(0 if report["ok"] else 1)


@release_app.command("supply-chain")
def release_supply_chain_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    artifact: Annotated[list[str] | None, typer.Option("--artifact")] = None,
    audit_report: str = typer.Option("", "--audit-report"),
    out_dir: str = typer.Option("dist/release-evidence", "--out-dir"),
) -> None:
    """Generate CycloneDX SBOM, provenance, hashes, and scan evidence."""
    from magent.supply_chain import build_supply_chain_evidence, write_supply_chain_bundle

    report = build_supply_chain_evidence(
        project, artifacts=artifact, audit_report=audit_report or None
    )
    report["files"] = write_supply_chain_bundle(report, out_dir)
    console.print_json(data=report)
    if not report["ok"]:
        raise typer.Exit(1)


@context_app.command("map")
def context_map_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    query: str = typer.Option("", "--query", "-q"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full machine-readable context payload."
    ),
):
    """Show memory, workbench, and project state for the current project."""
    from magent.context import context_map

    mgr, _ = command_context._get_memory_manager()
    data = context_map(_store(), project=project, memory_manager=mgr, query=query)
    if json_output:
        console.print_json(data=data)
        return
    _print_context_map(data)


@context_app.command("audit")
def context_audit_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    query: str = typer.Option("", "--query", "-q"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Audit active context and suggest token-saving cleanup actions."""
    from magent.context import context_map
    from magent.daily_driver import context_audit

    mgr, _ = command_context._get_memory_manager()
    data = context_audit(context_map(_store(), project=project, memory_manager=mgr, query=query))
    if json_output:
        console.print_json(data=data)
        return
    _print_context_map(data["data"])
    console.print("[bold]Context Hygiene Suggestions[/bold]")
    for item in data.get("suggestions", []):
        console.print(f"- {item}")


@recipe_app.command("list")
def recipe_list_cmd(project: str = typer.Option(".", "--project", "-p")):
    """List built-in, saved, and playbook-backed workflow recipes."""
    from magent.recipes import list_recipes

    table = Table("Name", "Source", "Commands", "Description")
    for item in list_recipes(_store(), project):
        table.add_row(
            item.get("name", ""),
            item.get("source", "builtin"),
            str(len(item.get("commands", []))),
            item.get("description", ""),
        )
    console.print(table)


@recipe_app.command("show")
def recipe_show_cmd(
    name: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Show a workflow recipe."""
    from magent.recipes import get_recipe

    recipe = get_recipe(_store(), name, project)
    if not recipe:
        console.print_json(data={"ok": False, "error": f"Recipe not found: {name}"})
        raise typer.Exit(1)
    console.print_json(data=recipe)


@recipe_app.command("save")
def recipe_save_cmd(
    name: str = typer.Argument(...),
    description: str = typer.Option("", "--description", "-d"),
    step: Annotated[
        list[str] | None, typer.Option("--step", help="Recipe step; may be repeated")
    ] = None,
    command: Annotated[
        list[str] | None,
        typer.Option("--command", "-c", help="Command; may be repeated"),
    ] = None,
):
    """Save a reusable workflow recipe."""
    from magent.recipes import save_recipe

    console.print_json(
        data=save_recipe(
            _store(), name, description=description, steps=step or [], commands=command or []
        )
    )


@recipe_app.command("run")
def recipe_run_cmd(
    name: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Create a pending execution plan from a workflow recipe."""
    from magent.recipes import run_recipe

    result = run_recipe(_store(), name, project)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@recipe_app.command("sandbox")
def recipe_sandbox_cmd(
    name: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    mode: str = typer.Option("worktree", "--mode"),
    run_checks: bool = typer.Option(False, "--run-checks"),
    keep: bool = typer.Option(False, "--keep"),
    image: str = typer.Option("python:3.12", "--image"),
):
    """Materialize a recipe and run it in a sandbox."""
    from magent.recipes import run_recipe
    from magent.sandbox import execute_plan_sandbox

    result = run_recipe(_store(), name, project)
    if not result.get("ok"):
        console.print_json(data=result)
        raise typer.Exit(1)
    plan_id = result["plan"]["id"]
    console.print_json(
        data={
            "ok": True,
            "recipe": result["recipe"],
            "plan": result["plan"],
            "sandbox": execute_plan_sandbox(
                _store(), plan_id, mode=mode, run_checks=run_checks, keep=keep, image=image
            ),
        }
    )


@skill_app.command("list")
def skill_list_cmd(project: str = typer.Option(".", "--project", "-p")):
    """List user and project skills available to MagAgent."""
    from magent.skills import SkillRegistry

    project_skills = Path(project).resolve() / ".magent" / "skills"
    registry = SkillRegistry(extra_dirs=[project_skills] if project_skills.exists() else None)
    registry.load(respect_lockfile=False)
    table = Table("Name", "Version", "Description", "Path")
    for item in registry.list_all():
        table.add_row(item["name"], item["version"], item["description"], item["path"])
    console.print(table)


@skill_app.command("search")
def skill_search_cmd(
    query: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Find skills relevant to a task or phrase."""
    from magent.skills import SkillRegistry

    project_skills = Path(project).resolve() / ".magent" / "skills"
    registry = SkillRegistry(extra_dirs=[project_skills] if project_skills.exists() else None)
    registry.load(respect_lockfile=False)
    table = Table("Name", "Score", "Description")
    scored = sorted(
        ((skill.score_relevance(query), skill) for skill in registry.skills),
        key=lambda item: item[0],
        reverse=True,
    )
    for score, skill in scored[:10]:
        if score <= 0:
            continue
        table.add_row(skill.name, f"{score:.2f}", skill.description[:100])
    console.print(table)


@skill_app.command("show")
def skill_show_cmd(
    name: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Show one local skill's metadata and path."""
    from magent.skills import SkillRegistry

    project_skills = Path(project).resolve() / ".magent" / "skills"
    registry = SkillRegistry(extra_dirs=[project_skills] if project_skills.exists() else None)
    registry.load(respect_lockfile=False)
    for skill in registry.skills:
        if skill.name == name:
            console.print_json(
                data={
                    "ok": True,
                    "name": skill.name,
                    "version": skill.version,
                    "description": skill.description,
                    "tools_required": skill.tools_required,
                    "path": str(skill.path),
                }
            )
            return
    console.print_json(data={"ok": False, "error": f"Skill not found: {name}"})
    raise typer.Exit(1)


@provider_app.command("list")
def provider_list_cmd():
    """List known providers and default models."""
    from magent.config_ux import provider_access_modes, provider_choices

    table = Table("Provider", "Default Model", "Access", "Description")
    for item in provider_choices():
        access = ", ".join(mode["id"] for mode in provider_access_modes(item["id"]))
        table.add_row(item["id"], item["default_model"], access, item["label"])
    console.print(table)


@provider_app.command("detect")
def provider_detect_cmd():
    """Detect likely provider readiness from local defaults and env vars."""
    from magent.config_ux import detect_provider_environment

    console.print_json(data={"ok": True, "providers": detect_provider_environment()})


@provider_app.command("set")
def provider_set_cmd(
    provider_id: str = typer.Argument(...),
    model: str | None = typer.Option(None, "--model", "-m"),
    api_key_env: str = typer.Option("", "--api-key-env"),
    api_key: str = typer.Option("", "--api-key"),
    api_key_keyring: str = typer.Option("", "--api-key-keyring"),
    base_url: str = typer.Option("", "--base-url"),
    team_id: str = typer.Option("", "--team-id", help="Optional provider team identifier"),
    access_mode: str = typer.Option(
        "", "--access", help="api, codex, payg, subscription, or local"
    ),
):
    """Set the default provider and model without editing config.toml."""
    from magent.config_ux import set_default_provider

    console.print_json(
        data=set_default_provider(
            provider_id,
            model,
            api_key_env=api_key_env,
            api_key=api_key,
            api_key_keyring=api_key_keyring,
            base_url=base_url,
            access_mode=access_mode,
            team_id=team_id,
        )
    )


@provider_app.command("wizard")
def provider_wizard_cmd():
    """Interactively configure provider, access mode, model, and key source."""
    from magent.cli.model_picker import prompt_for_provider_model
    from magent.cli.wizard_guidance import explain_options
    from magent.config_ux import provider_access_modes, provider_choices, set_default_provider
    from magent.provider_catalog import provider_env_vars

    console.print(
        Panel(
            "Choose the service used for ordinary MagAgent requests, how you access it, where its "
            "credential lives, and a model exposed by that provider.",
            title="Provider Wizard",
        )
    )
    choices = provider_choices()
    for i, item in enumerate(choices, 1):
        console.print(f"{i}. {item['id']} — {item['label']}")
    choice = Prompt.ask("Provider number", default="1")
    try:
        selected = choices[int(choice) - 1]
    except (ValueError, IndexError):
        selected = choices[0]
    modes = provider_access_modes(selected["id"])
    explain_options(
        console,
        "Access modes",
        [
            (str(i), f"{item['label']}: {item.get('description', item['id'])}")
            for i, item in enumerate(modes, 1)
        ],
        note="Access mode determines authentication and billing; it does not merely rename the provider.",
    )
    access_choice = Prompt.ask("Access mode", default="1")
    try:
        access_mode = modes[int(access_choice) - 1]["id"]
    except (ValueError, IndexError):
        access_mode = modes[0]["id"]
    team_id = ""
    if selected["id"] == "prime-intellect":
        team_id = Prompt.ask("Prime Intellect team ID (optional)", default="").strip()
    api_key_env = ""
    api_key = ""
    if access_mode not in {"codex", "local"}:
        default_env = provider_env_vars().get(selected["id"], "")
        console.print("[dim]Choose how MagAgent should find this provider credential.[/dim]")
        console.print("  [cyan]1[/cyan]. Paste key now and save it in MagAgent config")
        console.print(f"  [cyan]2[/cyan]. Use environment variable [bold]{default_env}[/bold]")
        console.print("  [cyan]3[/cyan]. Skip for now")
        console.print(
            "[dim]Pasted keys are stored locally with restrictive file permissions and redacted in "
            "config output. Environment variables keep the secret outside MagAgent config.[/dim]"
        )
        credential_choice = Prompt.ask("Credential option", choices=["1", "2", "3"], default="1")
        if credential_choice == "1":
            api_key = Prompt.ask("API key", password=True, default="").strip()
            if not api_key:
                console.print(
                    "[yellow]No key entered; falling back to environment variable setup.[/yellow]"
                )
                api_key_env = Prompt.ask("API key environment variable", default=default_env)
        elif credential_choice == "2":
            api_key_env = Prompt.ask("API key environment variable", default=default_env)
        else:
            console.print(
                f"[yellow]Skipping credential. You can add one later with "
                f"[bold]magent provider wizard[/bold] or [bold]magent provider set {selected['id']} --api-key-env {default_env}[/bold].[/yellow]"
            )
    base_url = ""
    if selected["id"] == "custom":
        base_url = Prompt.ask("API base URL", default="http://localhost:8000/v1").strip()
    resolved_key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
    model = prompt_for_provider_model(
        load_config(get_current_user()),
        store(),
        selected["id"],
        default_model=selected["default_model"],
        api_key=resolved_key,
        base_url=base_url or None,
        console=console,
    )
    result = set_default_provider(
        selected["id"],
        model,
        api_key_env=api_key_env,
        api_key=api_key,
        base_url=base_url,
        access_mode=access_mode,
        team_id=team_id,
    )
    console.print_json(data=result)


@provider_app.command("test")
def provider_test_cmd(
    provider_id: str | None = typer.Argument(None),
    model: str | None = typer.Option(None, "--model", "-m"),
):
    """Test a provider/model connection."""
    from magent.providers import test_provider

    username = get_current_user()
    config = load_config(username)
    provider_obj = _build_provider(config, provider_id, model)

    async def _run():
        return await test_provider(provider_obj)

    ok = asyncio.run(_run())
    console.print_json(
        data={
            "ok": ok,
            "provider": provider_obj.provider_id,
            "model": provider_obj.model,
        }
    )
    if not ok:
        raise typer.Exit(1)


@provider_app.command("doctor")
def provider_doctor_cmd():
    """Show provider, model-role, memory, gateway, and subagent readiness."""
    from magent.config_ux import ux_doctor

    console.print_json(data=ux_doctor(get_current_user()))


@provider_app.command("cooldowns")
def provider_cooldowns_cmd():
    """Show providers currently paused due to rate limits."""
    from magent.provider_cooldown import list_provider_cooldowns

    console.print_json(data=list_provider_cooldowns())


@provider_app.command("clear-cooldown")
def provider_clear_cooldown_cmd(provider_id: str = typer.Argument(...)):
    """Clear a provider cooldown."""
    from magent.provider_cooldown import clear_provider_cooldown

    console.print_json(data=clear_provider_cooldown(provider_id))


@model_app.command("roles")
def model_roles_cmd():
    """Show configured model roles."""
    from magent.config_ux import model_role_summary

    console.print_json(data=model_role_summary())


@model_app.command("set-role")
def model_set_role_cmd(role: str = typer.Argument(...), value: str = typer.Argument(...)):
    """Set a model role, e.g. coding openai/gpt-5."""
    from magent.config_ux import set_model_role

    result = set_model_role(role, value)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("clear-role")
def model_clear_role_cmd(role: str = typer.Argument(...)):
    """Clear a configured model role."""
    from magent.config_ux import clear_model_role

    result = clear_model_role(role)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("doctor")
def model_doctor_cmd():
    """Show model role readiness."""
    from magent.config_ux import ux_doctor

    console.print_json(
        data={"ok": True, "model_roles": ux_doctor(get_current_user())["model_roles"]}
    )


@model_app.command("orchestration-doctor")
def model_orchestration_doctor_cmd(
    planning_role: str = typer.Option("review", "--planning-role"),
    execution_role: str = typer.Option("coding", "--execution-role"),
):
    """Show planning/execution role readiness for orchestrated goals."""
    from magent.config_ux import orchestration_role_doctor

    result = orchestration_role_doctor(planning_role=planning_role, execution_role=execution_role)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("health")
def model_health_cmd():
    """Show model role provider/runtime health and recent live smoke observations."""
    from magent.config_ux import model_role_health
    from magent.model_health import model_health_report

    result = model_role_health()
    result["observations"] = model_health_report(_store())
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("capabilities")
def model_capabilities_cmd():
    """Show capability metadata for configured model roles."""
    from magent.model_capabilities import role_capability_summary

    config = load_config(get_current_user())
    console.print_json(data={"ok": True, "roles": role_capability_summary(config)})


@model_app.command("recommend")
def model_recommend_cmd(
    provider: str | None = typer.Option(None, "--provider", "-p"),
    task_type: str = typer.Option("tool-use", "--task-type", "-t"),
):
    """Recommend a model from successful local health observations."""
    from magent.model_health import recommend_model_from_health

    result = recommend_model_from_health(_store(), provider=provider, task_type=task_type)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("wizard")
def model_wizard_cmd():
    """Explain and configure specialized model roles."""
    from magent.cli.wizard_guidance import explain_options
    from magent.config_ux import MODEL_ROLES, set_model_role

    config = load_config(get_current_user())
    default = f"{config.default_provider}/{config.default_model}"
    explain_options(
        console,
        "Model roles",
        [
            ("coding", "Primary implementation and tool-use work."),
            ("review", "Independent code and change review."),
            ("memory", "Conversation-memory extraction and summarization."),
            ("cheap", "Low-cost background, routing, and lightweight tasks."),
            ("image_maker", "Image-generation requests when the provider supports them."),
            ("fallback", "Backup model used when the preferred model is unavailable."),
        ],
        note="Use provider/model values. Press Enter to inherit the displayed default; leave fallback blank to disable it.",
    )
    results = []
    for role in MODEL_ROLES:
        value = Prompt.ask(f"{role} model", default=default if role != "fallback" else "")
        if value:
            results.append(set_model_role(role, value))
    console.print_json(data={"ok": all(item.get("ok") for item in results), "results": results})


@model_app.command("image-wizard")
def model_image_wizard_cmd():
    """Interactively configure the image_maker model role and credentials."""
    from magent.cli.wizard_guidance import explain_field
    from magent.config_ux import (
        configure_provider_entry,
        image_model_choices,
        set_model_role,
    )
    from magent.provider_catalog import provider_env_vars

    explain_field(
        console,
        "Image model role",
        "Used only by image-generation tools. It does not replace your default chat or coding model.",
    )
    choices = image_model_choices()
    for i, item in enumerate(choices, 1):
        default = item["value"] or "provider/model"
        console.print(f"{i}. {item['label']} — {default}")
    choice = Prompt.ask("Image model", default="1")
    try:
        selected = choices[int(choice) - 1]
    except (ValueError, IndexError):
        selected = choices[0]

    if selected["id"] == "custom":
        provider_id = Prompt.ask("Provider id", default="openai").strip()
        model = Prompt.ask("Image model name", default="gpt-image-1").strip()
        value = f"{provider_id}/{model}" if provider_id and model else ""
        access_mode = Prompt.ask("Access mode", default="api").strip()
        default_env = provider_env_vars().get(provider_id, "")
    else:
        provider_id = selected["provider"]
        model = selected["model"]
        value = selected["value"]
        access_mode = selected["access_mode"]
        default_env = selected["api_key_env"]

    if not value:
        console.print_json(data={"ok": False, "error": "Image model must be provider/model."})
        raise typer.Exit(1)

    api_key_env = ""
    api_key = ""
    console.print("[dim]Choose how MagAgent should find this image provider credential.[/dim]")
    console.print("  [cyan]1[/cyan]. Paste key now and save it in MagAgent config")
    console.print(
        f"  [cyan]2[/cyan]. Use environment variable [bold]{default_env or 'PROVIDER_API_KEY'}[/bold]"
    )
    console.print("  [cyan]3[/cyan]. Skip credential setup")
    credential_choice = Prompt.ask("Credential option", choices=["1", "2", "3"], default="2")
    if credential_choice == "1":
        api_key = Prompt.ask("API key", password=True, default="").strip()
        if not api_key:
            console.print(
                "[yellow]No key entered; falling back to environment variable setup.[/yellow]"
            )
            api_key_env = Prompt.ask("API key environment variable", default=default_env)
    elif credential_choice == "2":
        api_key_env = Prompt.ask("API key environment variable", default=default_env)

    provider_result = configure_provider_entry(
        provider_id,
        model=model,
        api_key_env=api_key_env,
        api_key=api_key,
        access_mode=access_mode,
    )
    role_result = set_model_role("image_maker", value)
    result = {
        "ok": bool(provider_result.get("ok") and role_result.get("ok")),
        "provider": provider_result,
        "role": role_result,
        "next": "Run `magent model health` to verify credential readiness.",
    }
    console.print_json(data=result)
    if not result["ok"]:
        raise typer.Exit(1)


@auth_app.command("list")
def auth_list_cmd():
    """List configured provider credential sources."""
    from magent.auth_store import keyring_available, list_auth_entries

    config = load_config(get_current_user())
    console.print_json(
        data={
            "ok": True,
            "keyring_available": keyring_available(),
            "credentials": list_auth_entries(config.providers),
        }
    )


@auth_app.command("add")
def auth_add_cmd(
    provider_id: str = typer.Argument(...),
    api_key: str = typer.Option("", "--api-key", prompt=True, hide_input=True),
):
    """Store a provider API key in the OS keyring and reference it from config."""
    from magent.auth_store import keyring_account, save_keyring_secret
    from magent.config import load_global_config, save_global_config

    result = save_keyring_secret(provider_id, api_key)
    if result.get("ok"):
        cfg = load_global_config()
        entry = cfg.setdefault("providers", {}).setdefault(provider_id, {})
        entry.pop("api_key", None)
        entry["api_key_keyring"] = keyring_account(provider_id)
        save_global_config(cfg)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@auth_app.command("remove")
def auth_remove_cmd(provider_id: str = typer.Argument(...)):
    """Remove a provider API key from keyring/config references."""
    from magent.auth_store import delete_keyring_secret
    from magent.config import load_global_config, save_global_config

    result = delete_keyring_secret(provider_id)
    cfg = load_global_config()
    # Only touch a provider that was actually configured: setdefault created an
    # empty entry for providers that never existed, which then showed up as
    # `configured: true`.
    providers = cfg.get("providers") or {}
    entry = providers.get(provider_id)
    if isinstance(entry, dict) and entry.pop("api_key_keyring", None) is not None:
        save_global_config(cfg)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@config_app.command("validate")
def config_validate_cmd():
    """Validate provider, model-role, and instruction config."""
    from magent.config_validation import validate_config

    result = validate_config(get_current_user(), Path.cwd())
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@subagent_app.command("configure")
def subagent_configure_cmd(
    max_subagents: int | None = typer.Option(None, "--max"),
    max_parallel: int | None = typer.Option(None, "--parallel"),
    model_role: str = typer.Option("", "--model-role"),
    sandbox_mode: str = typer.Option("", "--sandbox-mode"),
):
    """Configure sub-agent caps and defaults."""
    from magent.config_ux import configure_subagents

    console.print_json(
        data=configure_subagents(
            max_subagents=max_subagents,
            max_parallel=max_parallel,
            model_role=model_role,
            sandbox_mode=sandbox_mode,
        )
    )


@subagent_app.command("status")
def subagent_status_cmd():
    """Show sub-agent configuration."""
    from magent.config_ux import ux_doctor

    console.print_json(data={"ok": True, "subagents": ux_doctor(get_current_user())["subagents"]})


@subagent_app.command("run")
def subagent_run_cmd(
    task: str = typer.Argument(...),
    provider: str | None = typer.Option(None, "--provider", "-p"),
    model: str | None = typer.Option(None, "--model", "-m"),
    project: str | None = typer.Option(None, "--project"),
):
    """Run one focused sub-agent task from the CLI."""
    username = _require_user()
    config = load_config(username)
    cwd = project or os.getcwd()
    main_provider = _build_provider(config, provider, model)
    extract_provider = _build_extraction_provider(config)

    async def _run():
        from magent.subagents import SubAgentRunner

        runner = SubAgentRunner(username, main_provider, extract_provider, cwd, config)
        result = await runner.spawn("cli_subagent", task)
        return result

    result = asyncio.run(_run())
    console.print_json(data=result.__dict__)


@subagent_app.command("wizard")
def subagent_wizard_cmd():
    """Explain and configure subagent caps, models, and isolation."""
    from magent.cli.wizard_guidance import explain_options
    from magent.config_ux import configure_subagents

    explain_options(
        console,
        "Subagent settings",
        [
            ("maximum", "Total focused workers the main agent may create for one task; 0 disables delegation."),
            ("parallel", "Workers allowed to run concurrently. Lower values reduce resource and quota spikes."),
            ("model role", "Configured model role used by workers, usually coding or cheap."),
            ("blank", "Run in the current project with normal checkpoint protections."),
            ("copy", "Use an isolated filesystem copy."),
            ("worktree", "Use an isolated Git worktree when the project is a repository."),
            ("container", "Use the configured container runtime for strongest isolation."),
        ],
        note="Profile-specific subagent limits can narrow these global caps but cannot raise them.",
    )
    max_subagents = int(Prompt.ask("Maximum sub-agents", default="3"))
    max_parallel = int(Prompt.ask("Maximum parallel sub-agents", default="2"))
    model_role = Prompt.ask("Model role", default="coding")
    sandbox_mode = Prompt.ask("Sandbox mode (blank, copy, worktree, container)", default="")
    console.print_json(
        data=configure_subagents(
            max_subagents=max_subagents,
            max_parallel=max_parallel,
            model_role=model_role,
            sandbox_mode=sandbox_mode,
        )
    )


@app.command("env-doctor", rich_help_panel="Performance & Diagnostics")
def env_doctor_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Run project environment checks."""
    from magent.workbench import env_doctor

    table = Table("Check", "OK", "Detail")
    for check in env_doctor(project):
        table.add_row(check["check"], "yes" if check["ok"] else "no", check.get("detail", ""))
    console.print(table)


@app.command("ci", rich_help_panel="Integrations")
def ci_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    logs: bool = typer.Option(False, "--logs", help="Include failed-run logs and repair hints"),
    repair_plan: bool = typer.Option(False, "--repair-plan", help="Include a local CI repair plan"),
    save: bool = typer.Option(False, "--save", help="Save repair plan to the plan ledger"),
):
    """Triage recent GitHub Actions runs with gh, when available."""
    from magent.workbench import ci_triage

    console.print_json(
        data=ci_triage(project, logs=logs, repair_plan=repair_plan, store=_store(), save=save)
    )


@app.command("diagnostics", rich_help_panel="Performance & Diagnostics")
def diagnostics_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    deep: bool = typer.Option(
        False, "--deep", help="Include provider, MCP, hooks, plugins, and permissions."
    ),
    prompt: str = typer.Option(
        "", "--prompt", help="Optional prompt to verify expected artifacts from."
    ),
):
    """Run available local diagnostics for the current project."""
    if deep:
        from magent.diagnostics import deep_diagnostics

        username = _require_user()
        console.print_json(
            data=deep_diagnostics(
                username, load_config(username), _store(), project=project, prompt=prompt
            )
        )
        return
    from magent.workbench import project_diagnostics

    console.print_json(data=project_diagnostics(project, store=_store()))


@app.command("docs-brief", rich_help_panel="Help & Learning")
def docs_brief_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    out: str | None = typer.Option(None, "--out"),
):
    """Generate a compact project documentation brief."""
    from magent.workbench import docs_brief

    text = docs_brief(project)
    if out:
        Path(out).write_text(text)
        console.print(f"[green]✓ Wrote {out}[/green]")
    else:
        console.print(text)


@app.command("tutorial", rich_help_panel="Start Here")
def tutorial_cmd():
    """Show the built-in getting-started tutorial."""
    from magent.docs import read_topic

    console.print(read_topic("tutorial"))


@app.command("get-started", rich_help_panel="Start Here")
def get_started_cmd(
    json_output: bool = typer.Option(False, "--json", help="Return the guide and key commands as JSON."),
):
    """Show a clear first-use guide for MagAgent."""
    from rich.markdown import Markdown

    from magent.docs import read_topic

    guide = read_topic("get-started")
    if json_output:
        console.print_json(
            data={
                "ok": True,
                "guide": guide,
                "first_commands": [
                    "magent configure",
                    "magent doctor",
                    "magent",
                    'magent ask "task"',
                    "magent profile wizard",
                    "magent docs search <query>",
                ],
            }
        )
        return
    console.print(Markdown(guide))


@data_app.command("inspect")
def data_inspect_cmd(path: str = typer.Argument(...)):
    """Inspect a CSV or SQLite file."""
    from magent.workbench import inspect_data

    console.print_json(data=inspect_data(path))


@data_app.command("sqlite-list")
def data_sqlite_list_cmd(user: str | None = typer.Option(None, "--user", "-u")):
    """List MagAgent SQLite databases for desktop browsing."""
    from magent.desktop_api import sqlite_list

    console.print_json(data=sqlite_list(user or _require_user()))


@data_app.command("sqlite-tables")
def data_sqlite_tables_cmd(
    db_name: str = typer.Option("default", "--db", help="Database name."),
    user: str | None = typer.Option(None, "--user", "-u"),
):
    """List tables and row counts in a MagAgent SQLite database."""
    from magent.desktop_api import sqlite_tables

    console.print_json(data=sqlite_tables(user or _require_user(), db_name))


@data_app.command("sqlite-schema")
def data_sqlite_schema_cmd(
    table: str = typer.Argument(...),
    db_name: str = typer.Option("default", "--db", help="Database name."),
    user: str | None = typer.Option(None, "--user", "-u"),
):
    """Show SQLite table schema for desktop browsing."""
    from magent.desktop_api import sqlite_table_schema

    result = sqlite_table_schema(user or _require_user(), table, db_name)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@data_app.command("sqlite-query")
def data_sqlite_query_cmd(
    sql: str = typer.Argument(...),
    db_name: str = typer.Option("default", "--db", help="Database name."),
    params: str = typer.Option("[]", "--params", help="JSON array of query params."),
    user: str | None = typer.Option(None, "--user", "-u"),
):
    """Run a read-only SELECT/WITH query against a MagAgent SQLite database."""
    from magent.desktop_api import parse_json_value, sqlite_query

    parsed = parse_json_value(params)
    result = sqlite_query(
        user or _require_user(), sql, db_name, parsed if isinstance(parsed, list) else []
    )
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@api_app.command("save")
def api_save_cmd(
    name: str = typer.Argument(...),
    method: str = typer.Argument(...),
    url: str = typer.Argument(...),
):
    """Save an API endpoint bookmark."""
    item = _store().append("api_endpoints", {"name": name, "method": method.upper(), "url": url})
    console.print(f"[green]✓ Saved {item['id']}[/green]")


@api_app.command("list")
def api_list_cmd():
    """List API endpoint bookmarks."""
    table = Table("ID", "Name", "Method", "URL")
    for item in _store().read("api_endpoints", []):
        table.add_row(item["id"], item.get("name", ""), item.get("method", ""), item.get("url", ""))
    console.print(table)


@app.command("notes", rich_help_panel="Workbench & Productivity")
def notes_cmd(path: str = typer.Argument(...)):
    """Ingest meeting/working notes and extract tasks/decisions."""
    from magent.workbench import ingest_notes

    text = Path(path).read_text(encoding="utf-8")
    console.print_json(data=ingest_notes(_store(), text))


@session_app.command("timeline")
def session_timeline_cmd(session_id: str | None = typer.Argument(None)):
    """Show a recent session action timeline."""
    from magent.workbench import session_timeline

    events = session_timeline(session_id)
    table = Table("Time", "Event", "Details")
    for event in events:
        detail = {k: v for k, v in event.items() if k not in {"ts", "event", "session"}}
        table.add_row(event.get("ts", "")[:19], event.get("event", ""), str(detail)[:120])
    console.print(table)


@session_app.command("events")
def session_events_cmd(
    log_path: str | None = typer.Argument(
        None, help="Session JSONL path. Defaults to the newest log."
    ),
    limit: int = typer.Option(200, "--limit", "-n"),
    event_type: Annotated[
        list[str] | None, typer.Option("--type", help="Filter event type.")
    ] = None,
):
    """Show normalized session events for UI and diagnostics."""
    from magent.config import LOGS_DIR
    from magent.session_controls import session_event_stream

    target = Path(log_path) if log_path else None
    if target is None:
        logs = sorted(LOGS_DIR.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not logs:
            console.print_json(data={"ok": False, "error": "No session logs found"})
            raise typer.Exit(1)
        target = logs[0]
    console.print_json(data=session_event_stream(target, limit=limit, event_types=event_type))


@session_app.command("peers")
def session_peers_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    include_stale: bool = typer.Option(False, "--include-stale"),
):
    """List reachable local MagAgent sessions."""
    from magent.session_messaging import list_sessions

    peers = list_sessions(_require_user(), include_stale=include_stale)
    if json_output:
        console.print_json(data={"ok": True, "sessions": peers, "count": len(peers)})
        return
    _print_session_peers(peers)


@session_app.command("send")
def session_send_cmd(
    target: str = typer.Argument(..., help="Durable session ID or unambiguous name."),
    message: str = typer.Argument(..., help="Plain-text coordination message."),
    task_id: str = typer.Option("", "--task"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Send a message to a live local session."""
    from magent.session_messaging import register_ephemeral_sender, send_session_message

    username = _require_user()
    sender_id, cleanup = register_ephemeral_sender(username, cwd=os.getcwd())
    try:
        result = send_session_message(username, sender_id, target, message, task_id=task_id)
    finally:
        cleanup()
    if json_output:
        console.print_json(data=result)
    else:
        _print_session_receipt(result)
    if not result.get("ok"):
        raise typer.Exit(1)


@session_app.command("inbox")
def session_inbox_cmd(
    session_id: str = typer.Argument(...),
    held: bool = typer.Option(False, "--held", help="Show messages awaiting review."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Inspect a session's accepted or held local messages."""
    from magent.session_messaging import session_inbox

    items = session_inbox(_require_user(), session_id, held=held)
    if json_output:
        console.print_json(data={"ok": True, "messages": items, "count": len(items)})
        return
    _print_session_inbox(items, held=held)


def _review_session_message(session_id: str, message_id: str, decision: str) -> None:
    from magent.session_messaging import review_held_message

    result = review_held_message(_require_user(), session_id, message_id, decision)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@session_app.command("accept")
def session_accept_cmd(
    session_id: str = typer.Argument(...), message_id: str = typer.Argument(...)
):
    """Move a held peer message into the accepted inbox."""
    _review_session_message(session_id, message_id, "accept")


@session_app.command("refuse")
def session_refuse_cmd(
    session_id: str = typer.Argument(...), message_id: str = typer.Argument(...)
):
    """Discard a held peer message."""
    _review_session_message(session_id, message_id, "refuse")


@session_app.command("policy")
def session_policy_cmd(
    policy: str = typer.Argument(..., help="accept, hold, or refuse"),
    headless_accept: bool = typer.Option(False, "--headless-accept/--no-headless-accept"),
):
    """Configure the default receiving policy for future sessions."""
    from magent.config import load_global_config, save_global_config
    from magent.session_messaging import VALID_POLICIES

    if policy not in VALID_POLICIES:
        console.print("[red]Policy must be accept, hold, or refuse.[/red]")
        raise typer.Exit(2)
    cfg = load_global_config()
    settings = cfg.setdefault("session_messaging", {})
    settings["policy"] = policy
    settings["headless_accept"] = headless_accept
    save_global_config(cfg)
    console.print_json(data={"ok": True, "session_messaging": settings})


@session_app.command("receipts")
def session_receipts_cmd(
    sender_id: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show delivery receipts for a session sender."""
    from magent.session_messaging import session_receipts

    items = session_receipts(_require_user(), sender_id)
    if json_output:
        console.print_json(data={"ok": True, "receipts": items, "count": len(items)})
        return
    _print_session_receipts(items)


@session_app.command("retry")
def session_retry_cmd(sender_id: str = typer.Argument(...)):
    """Retry unreachable messages from a live session's durable outbox."""
    from magent.session_messaging import retry_outbox

    result = retry_outbox(_require_user(), sender_id)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@session_app.command("doctor")
def session_doctor_cmd():
    """Check local session messaging policy, storage, roster, and queues."""
    from magent.session_messaging import messaging_diagnostics

    username = _require_user()
    result = messaging_diagnostics(username, load_config(username))
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("stats", rich_help_panel="Performance & Diagnostics")
def stats_cmd():
    """Show approximate local usage and token stats."""
    from magent.workbench import usage_stats

    console.print_json(data=usage_stats())


@policy_app.command("list")
def policy_list_cmd():
    """List built-in policy profiles."""
    from magent.workbench import policy_profiles

    console.print_json(data=policy_profiles())


def _block_until_interrupt(server: Any = None) -> None:
    """Wait for Ctrl+C, then shut the server down.

    `signal.pause()` does not exist on Windows, so the AttributeError path
    returned immediately and the server died the moment it started.
    """
    import threading

    stop = threading.Event()
    try:
        # A bare wait() is not interruptible by Ctrl+C on Windows, so poll.
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            with contextlib.suppress(Exception):
                server.shutdown()
            with contextlib.suppress(Exception):
                server.server_close()


@app.command("dashboard", rich_help_panel="Data & Local UI")
def dashboard_cmd(
    out: str = typer.Option("magent-dashboard.html", "--out"),
    serve: bool = typer.Option(False, "--serve"),
    port: int = typer.Option(7820, "--port"),
    open_browser: bool = typer.Option(False, "--open"),
):
    """Export or serve a local workbench dashboard."""
    from magent.workbench import export_dashboard, serve_dashboard

    if serve:
        result = serve_dashboard(_store(), port=port, open_browser=open_browser)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
        console.print("[dim]Press Ctrl+C to stop.[/dim]")
        _block_until_interrupt(result.get("server"))
        return
    path = export_dashboard(_store(), out)
    console.print(f"[green]✓ Dashboard written to {path}[/green]")


@app.command("ui", rich_help_panel="Data & Local UI")
def ui_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    port: int = typer.Option(7830, "--port"),
    open_browser: bool = typer.Option(False, "--open"),
):
    """Serve the local operations UI."""
    from magent.ui import serve_ui

    username = _require_user()
    result = serve_ui(
        _store(), project=project, username=username, port=port, open_browser=open_browser
    )
    console.print_json(data={key: value for key, value in result.items() if key != "server"})
    if not result.get("ok"):
        raise typer.Exit(1)
    console.print("[dim]Press Ctrl+C to stop.[/dim]")
    _block_until_interrupt(result.get("server"))
    return


@checkpoint_app.command("list")
def checkpoint_list_cmd(
    limit: int = typer.Option(20, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """List recent file checkpoints."""
    from magent.workbench import list_checkpoints

    items = list_checkpoints(_store(), limit=limit)
    if json_output:
        console.print_json(data={"ok": True, "checkpoints": items, "count": len(items)})
        return
    table = Table("ID", "Operation", "Status", "Path")
    for item in items:
        table.add_row(
            item.get("id", ""),
            item.get("operation", ""),
            item.get("status", ""),
            item.get("path", "")[:100],
        )
    console.print(table)


@checkpoint_app.command("show")
def checkpoint_show_cmd(checkpoint_id: str = typer.Argument(...)):
    """Show checkpoint metadata."""
    from magent.workbench import show_checkpoint

    item = show_checkpoint(_store(), checkpoint_id)
    if not item:
        console.print(f"[red]Checkpoint not found: {checkpoint_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@checkpoint_app.command("diff")
def checkpoint_diff_cmd(
    checkpoint_id: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Show a diff from checkpoint contents to current file contents."""
    from magent.workbench import checkpoint_diff

    result = checkpoint_diff(_store(), checkpoint_id)
    if not result.get("ok"):
        console.print_json(data=result)
        raise typer.Exit(1)
    if json_output:
        console.print_json(data=result)
        return
    console.print(result.get("diff") or "[dim]No diff.[/dim]")


@checkpoint_app.command("restore")
def checkpoint_restore_cmd(
    checkpoint_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Restore a checkpoint."""
    from magent.workbench import restore_checkpoint

    if not yes:
        confirm = Prompt.ask(
            f"Restore checkpoint '{checkpoint_id}'?", choices=["y", "n"], default="n"
        )
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=restore_checkpoint(_store(), checkpoint_id))


@checkpoint_app.command("restore-last")
def checkpoint_restore_last_cmd(yes: bool = typer.Option(False, "--yes", "-y")):
    """Restore the most recent checkpoint."""
    from magent.workbench import restore_latest_checkpoint

    if not yes:
        confirm = Prompt.ask("Restore the latest checkpoint?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=restore_latest_checkpoint(_store()))


@checkpoint_app.command("session-list")
def checkpoint_session_list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """List checkpoint sessions."""
    from magent.workbench import checkpoint_sessions

    items = checkpoint_sessions(_store())
    if json_output:
        console.print_json(data={"ok": True, "sessions": items, "count": len(items)})
        return
    table = Table("Session", "Count", "Last", "Paths")
    for item in items:
        table.add_row(
            item.get("session_id", ""),
            str(item.get("count", 0)),
            item.get("last_at", "")[:19],
            ", ".join(item.get("paths", []))[:120],
        )
    console.print(table)


@checkpoint_app.command("session-diff")
def checkpoint_session_diff_cmd(
    session_id: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Show combined diffs for a checkpoint session."""
    from magent.workbench import checkpoint_session_diff

    result = checkpoint_session_diff(_store(), session_id)
    if json_output:
        console.print_json(data=result)
        return
    console.print(result.get("diff") or "[dim]No diff.[/dim]")


@checkpoint_app.command("session-restore")
def checkpoint_session_restore_cmd(
    session_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Restore all checkpoints for a session in reverse order."""
    from magent.workbench import checkpoint_session_restore

    if not yes:
        confirm = Prompt.ask(
            f"Restore checkpoint session '{session_id}'?", choices=["y", "n"], default="n"
        )
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=checkpoint_session_restore(_store(), session_id))


register_memory_commands(
    memory_app,
    memory_semantic_app,
    user_app,
    # Late-bound on purpose: these resolve from this module's globals on each
    # call, so patching `cli_main._store` still reaches the extracted commands.
    store=lambda: _store(),
    require_user=lambda: _require_user(),
    get_memory_manager=lambda: command_context._get_memory_manager(),
)


@app.command("setup", rich_help_panel="Start Here")
def setup():
    """First-time setup wizard."""
    from magent.setup import run_setup

    run_setup()


@app.command("configure", rich_help_panel="Start Here")
def configure_cmd():
    """Run the friendly configuration wizard."""
    from magent.setup import run_setup

    run_setup()


@app.command("onboard", rich_help_panel="Start Here")
def onboard_cmd(
    profile: str = typer.Option("coding-local", "--profile"),
    project: str = typer.Option(".", "--project", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply defaults without prompts"),
):
    """Guide a user through core MagAgent readiness."""
    from magent.ux_flows import apply_profile, init_project

    username = _require_user()
    selected = profile
    if not yes:
        selected = Prompt.ask("Configuration profile", default=profile)
    profile_result = apply_profile(selected, username)
    project_result = init_project(project)
    console.print_json(
        data={
            "ok": bool(profile_result.get("ok") and project_result.get("ok")),
            "profile": profile_result,
            "project": project_result,
            "next": ["magent doctor --json", "magent provider test", "magent next"],
        }
    )


@app.command("next", rich_help_panel="Start Here")
def next_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Suggest useful next actions for the current repo and MagAgent setup."""
    from magent.ux_flows import next_actions

    console.print_json(data=next_actions(project, store=_store(), username=get_current_user()))


@profile_app.command("list")
def profile_list_cmd():
    """List guided configuration presets."""
    from magent.ux_flows import list_profiles

    console.print_json(data=list_profiles())


@profile_app.command("apply")
def profile_apply_cmd(name: str = typer.Argument(...)):
    """Apply a guided provider/memory/subagent preset."""
    from magent.ux_flows import apply_profile

    result = apply_profile(name, get_current_user())
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("mode", rich_help_panel="Setup & Configuration")
def set_mode(
    mode: str = typer.Argument(..., help="Permission mode: silent|balanced|paranoid|yolo"),
):
    """Set the default permission mode for the current user."""
    valid = ("silent", "balanced", "paranoid", "yolo")
    if mode not in valid:
        console.print(f"[red]Invalid mode '{mode}'. Choose: {', '.join(valid)}[/red]")
        raise typer.Exit(1)
    username = _require_user()
    from magent.config import load_user_profile, save_user_profile

    profile = load_user_profile(username)
    profile.setdefault("permissions", {})["mode"] = mode
    save_user_profile(username, profile)
    console.print(f"[green]✓ Permission mode set to [bold]{mode}[/bold][/green]")


@app.command("doctor", rich_help_panel="Start Here")
def doctor(
    fix: bool = typer.Option(False, "--fix", help="Apply safe local fixes for missing UX defaults"),
    json_output: bool = typer.Option(False, "--json", help="Emit structured doctor actions only"),
):
    """Run health checks: providers, maggraph, config."""
    from magent.config_ux import doctor_actions, fix_doctor_actions
    from magent.utils import run_doctor

    if fix:
        payload = fix_doctor_actions(get_current_user())
        console.print_json(data=payload)
        return
    payload = doctor_actions(get_current_user())
    if json_output:
        console.print_json(data=payload)
        return
    run_doctor()
    table = Table("UX Check", "OK", "Detail", "Try")
    for item in payload["actions"]:
        table.add_row(
            item["key"],
            "yes" if item["ok"] else "no",
            item["detail"],
            item.get("command", ""),
        )
    console.print(table)


@app.command("readiness", rich_help_panel="Start Here")
def readiness_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    smoke: bool = typer.Option(False, "--smoke", help="Run a tiny live provider tool-use smoke."),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    timeout: int = typer.Option(90, "--timeout", help="Maximum smoke runtime in seconds."),
):
    """Show one concise setup, docs, project, provider, and model readiness report."""
    from magent.readiness import readiness_report

    username = _require_user()
    config = load_config(username)
    result = readiness_report(
        username,
        config,
        _store(),
        project=project,
        smoke=smoke,
        provider_id=provider,
        model=model,
        smoke_timeout=timeout,
    )
    console.print_json(data=result)


# ─────────────────────────────────────────────
# Gateway subcommands
# ─────────────────────────────────────────────


@gateway_app.command("start")
def gateway_start(
    platforms: Annotated[
        list[str] | None,
        typer.Argument(help="Platforms to start: slack discord telegram (default: all configured)"),
    ] = None,
    foreground: bool = typer.Option(
        False,
        "--foreground",
        "-f",
        help="Run in foreground instead of background daemon",
    ),
):
    """
    Start the remote gateway on one or more platforms.

    Examples:
      magent gateway start                  # all configured platforms
      magent gateway start slack telegram   # specific platforms
      magent gateway start discord -f       # foreground (for debugging)
    """
    from magent.gateway import GATEWAY_LOG_FILE, GatewayRunner, is_gateway_running

    running, pid = is_gateway_running()
    if running:
        console.print(f"[yellow]Gateway already running (PID {pid})[/yellow]")
        raise typer.Exit(1)

    username = _require_user()
    config_data = load_config(username).as_dict()

    gw_cfg = config_data.get("gateway", {})
    if not gw_cfg:
        console.print(
            "[red]No [gateway] section in config.toml.\n"
            "Run [bold]magent gateway init[/bold] to generate an example config.[/red]"
        )
        raise typer.Exit(1)

    # Determine which platforms to start
    if not platforms:
        platforms = [
            p for p in ("slack", "discord", "telegram") if gw_cfg.get(p, {}).get("bot_token")
        ]
        if not platforms:
            console.print(
                "[red]No platform tokens found in [gateway.*] config.\n"
                "Add bot_token values or specify platforms explicitly.[/red]"
            )
            raise typer.Exit(1)

    runner = GatewayRunner(config_data)

    if foreground:
        console.print(f"[bold]Starting gateway in foreground on: {', '.join(platforms)}[/bold]")
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(runner.run(platforms))
        return

    # Background daemon via subprocess
    import subprocess as _sp

    GATEWAY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "magent.gateway._daemon"] + platforms
    with open(GATEWAY_LOG_FILE, "a") as logf:
        proc = _sp.Popen(
            cmd,
            stdout=logf,
            stderr=logf,
            start_new_session=True,
        )
    console.print(
        f"[bold green]✓ Gateway started (PID {proc.pid}) on: {', '.join(platforms)}[/bold green]"
    )
    console.print(f"[dim]Logs: {GATEWAY_LOG_FILE}[/dim]")
    console.print("[dim]Stop with: magent gateway stop[/dim]")


@gateway_app.command("stop")
def gateway_stop():
    """Stop the running gateway daemon."""
    import signal as _sig

    from magent.gateway import GATEWAY_PID_FILE, is_gateway_running

    running, pid = is_gateway_running()
    if not running or pid is None:
        console.print("[dim]No gateway is running.[/dim]")
        raise typer.Exit()

    try:
        os.kill(pid, _sig.SIGTERM)
        GATEWAY_PID_FILE.unlink(missing_ok=True)
        console.print(f"[green]✓ Gateway (PID {pid}) stopped.[/green]")
    except Exception as e:
        console.print(f"[red]Failed to stop gateway: {e}[/red]")
        raise typer.Exit(1) from e


@gateway_app.command("status")
def gateway_status(
    sessions: bool = typer.Option(
        False, "--sessions", help="Show configured access and live session state."
    ),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show whether the gateway is running and on which platforms."""
    from magent.gateway import GATEWAY_LOG_FILE, is_gateway_running

    running, pid = is_gateway_running()
    payload: dict[str, Any] = {"running": running, "pid": pid, "log": str(GATEWAY_LOG_FILE)}

    if sessions:
        # The gateway runs in its own process, so its live sessions are not
        # reachable from here; report the access posture, which is what an
        # operator needs to answer "who can drive this?".
        from magent.gateway import read_gateway_config
        from magent.gateway.router import MessageRouter

        try:
            config = load_config(get_current_user() or "default")
            router = MessageRouter(
                read_gateway_config(config.raw() if hasattr(config, "raw") else {})
            )
            payload["access"] = router.session_report()
        except Exception as error:
            payload["access"] = {"ok": False, "error": str(error)}

    if json_output:
        console.print_json(data=payload)
        return

    if running:
        console.print(f"[bold green]● Gateway running[/bold green] (PID {pid})")
        console.print(f"[dim]Logs: {GATEWAY_LOG_FILE}[/dim]")
    else:
        console.print("[dim]○ Gateway is not running.[/dim]")

    access = payload.get("access")
    if access and access.get("ok"):
        allowed = access.get("allowed_user_ids") or []
        console.print(
            "[dim]access:[/dim] "
            + (f"{len(allowed)} allow-listed user(s)" if allowed else "[red]no allowlist[/red]")
            + (" [red](allow_anyone)[/red]" if access.get("allow_anyone") else "")
            + (" · require_mention" if access.get("require_mention") else "")
        )
    elif access:
        console.print(f"[yellow]access: {access.get('error')}[/yellow]")


@gateway_app.command("init")
def gateway_init():
    """Print an example [gateway] config block to add to config.toml."""
    from magent.config import CONFIG_DIR
    from magent.gateway import EXAMPLE_GATEWAY_CONFIG

    config_path = CONFIG_DIR / "config.toml"
    console.print(
        Panel(
            EXAMPLE_GATEWAY_CONFIG.strip(),
            title="[bold cyan]Example Gateway Config[/bold cyan]",
            subtitle=f"Add to {config_path}",
        )
    )


@gateway_app.command("configure")
def gateway_configure_cmd(
    platform: str = typer.Argument(..., help="slack, discord, or telegram"),
    bot_token: str = typer.Option("", "--bot-token"),
    app_token: str = typer.Option("", "--app-token", help="Slack Socket Mode app token"),
    allowed_user: Annotated[list[str] | None, typer.Option("--allowed-user")] = None,
    allowed_channel: Annotated[list[str] | None, typer.Option("--allowed-channel")] = None,
    rate_limit: int | None = typer.Option(None, "--rate-limit"),
    timeout: int | None = typer.Option(None, "--timeout"),
):
    """Configure a gateway platform without hand-editing config.toml."""
    from magent.config_ux import configure_gateway

    result = configure_gateway(
        platform,
        bot_token=bot_token,
        app_token=app_token,
        allowed_user_ids=allowed_user,
        allowed_channel_ids=allowed_channel,
        rate_limit=rate_limit,
        timeout_seconds=timeout,
    )
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@gateway_app.command("wizard")
def gateway_wizard_cmd(platform: str = typer.Argument(..., help="slack, discord, or telegram")):
    """Configure gateway tokens and user/channel allowlists."""
    from magent.cli.wizard_guidance import explain_field
    from magent.config_ux import configure_gateway

    platform = platform.lower()
    explain_field(
        console,
        "Gateway security",
        "Tokens authenticate the bot. User and channel allowlists determine who may send work to your agent; leaving both blank is not recommended for public bots.",
    )
    bot_token = Prompt.ask(f"{platform} bot token", password=True, default="")
    app_token = ""
    if platform == "slack":
        app_token = Prompt.ask("Slack app token (xapp-...)", password=True, default="")
    allowed_users = [
        item.strip()
        for item in Prompt.ask("Allowed user IDs (comma-separated, optional)", default="").split(",")
        if item.strip()
    ]
    allowed_channels = [
        item.strip()
        for item in Prompt.ask("Allowed channel IDs (comma-separated, optional)", default="").split(",")
        if item.strip()
    ]
    console.print(
        "[dim]Use platform-native IDs, not display names. Run magent gateway doctor after setup.[/dim]"
    )
    result = configure_gateway(
        platform,
        bot_token=bot_token,
        app_token=app_token,
        allowed_user_ids=allowed_users,
        allowed_channel_ids=allowed_channels,
    )
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@gateway_app.command("doctor")
def gateway_doctor_cmd():
    """Show gateway configuration readiness."""
    from magent.config_ux import ux_doctor

    console.print_json(data={"ok": True, "gateways": ux_doctor(get_current_user())["gateways"]})


@gateway_app.command("logs")
def gateway_logs(
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
):
    """Show gateway log output."""
    from magent.gateway import GATEWAY_LOG_FILE

    if not GATEWAY_LOG_FILE.exists():
        console.print("[dim]No gateway log file found.[/dim]")
        raise typer.Exit()

    if follow:
        import subprocess as _sp

        with contextlib.suppress(KeyboardInterrupt):
            _sp.run(["tail", "-f", str(GATEWAY_LOG_FILE)])
        return

    lines = GATEWAY_LOG_FILE.read_text().splitlines()
    for line in lines[-tail:]:
        console.print(line)


# ─────────────────────────────────────────────
# MCP COMMANDS
# ─────────────────────────────────────────────

EXAMPLE_MCP_CONFIG = """
# Add to ~/.config/magent/config.toml:

[mcp.servers.github]
transport = "stdio"
protocol_mode = "auto" # auto | modern | legacy
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "ghp_your_token_here" }

[mcp.servers.filesystem]
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]

[mcp.servers.postgres]
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"]
timeout = 60

# Modern Streamable HTTP configuration:
# [mcp.servers.remote]
# transport = "streamable-http"
# protocol_mode = "modern"
# url = "https://example.com/mcp"
# headers = { Authorization = "Bearer ${MCP_TOKEN}" }

# Browse more servers: https://github.com/modelcontextprotocol/servers
"""


@mcp_app.command("list")
def mcp_list(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full tool schemas"),
) -> None:
    """List all configured MCP servers and their available tools."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user. Run 'magent setup' first.[/red]")
        raise typer.Exit(1)

    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if not mcp_servers:
        console.print("[yellow]No MCP servers configured.[/yellow]")
        console.print("\nExample config:")
        console.print(EXAMPLE_MCP_CONFIG, markup=False, highlight=False)
        return

    async def _list() -> None:
        from magent.mcp import MCPManager

        manager = MCPManager(mcp_servers)
        console.print(f"\n[bold]Connecting to {len(mcp_servers)} MCP server(s)...[/bold]")
        await manager.start_all()

        for server_info in manager.list_servers():
            name = server_info["name"]
            ok = server_info["connected"]
            endpoint = server_info["endpoint"]
            transport = server_info["transport"]
            configured_mode = server_info["protocol_mode"]
            selected_era = server_info["selected_era"] or "-"
            protocol_version = server_info["protocol_version"] or "-"
            tools = server_info["tools"]
            error = server_info["error"]

            icon = "[green]●[/green]" if ok else "[red]●[/red]"
            console.print(f"\n  {icon} [bold]{name}[/bold]  [dim]{endpoint}[/dim]")
            console.print(
                f"    [dim]transport={transport} configured={configured_mode} "
                f"selected={selected_era} version={protocol_version}[/dim]"
            )

            if ok and tools:
                table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
                table.add_column("Tool", style="white")
                table.add_column("Qualified Name", style="dim")
                table.add_column("Description")
                for tool in manager.tools_for(name):
                    table.add_row(
                        tool.name,
                        tool.qualified_name,
                        (tool.description or "-")[:80],
                    )
                console.print(table)
            elif not ok:
                console.print(f"    [red]{error or 'Connection failed'}[/red]")
            else:
                console.print("    [dim](no tools)[/dim]")

        await manager.stop_all()

    asyncio.run(_list())


@mcp_app.command("test")
def mcp_test(
    server: str = typer.Argument(..., help="Server name from config (e.g. github)"),
) -> None:
    """Test connection to a specific MCP server and list its tools."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)

    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        console.print(f"Configured: {list(mcp_servers.keys()) or '(none)'}")
        raise typer.Exit(1)

    async def _test() -> None:
        from magent.mcp import MCPClient, MCPConfigError, MCPServerProfile

        srv_cfg = mcp_servers[server]
        try:
            profile = MCPServerProfile.from_config(server, srv_cfg)
        except MCPConfigError as exc:
            console.print(f"[red]Invalid MCP configuration: {exc}[/red]")
            raise typer.Exit(1) from exc
        client = MCPClient.from_profile(profile)
        console.print(f"\nConnecting to [bold]{server}[/bold]...")
        console.print(
            f"[dim]transport={profile.transport.value} "
            f"protocol_mode={profile.protocol_mode.value} endpoint={profile.public_endpoint}[/dim]"
        )
        ok = await client.connect()
        # From here on the server subprocess exists, so every exit path has to
        # disconnect — including the failure paths, which used to leak it.
        try:
            if not ok:
                console.print(f"[red]✗ {client.last_error or 'Connection failed.'}[/red]")
                raise typer.Exit(1)

            console.print(
                f"[green]✓ Connected using {client.selected_era} MCP "
                f"({client.selected_protocol_version}) — {len(client.tools)} tools:[/green]"
            )
            for tool in client.tools:
                console.print(f"  [bold]{tool.name}[/bold] — {tool.description}")
                console.print(f"    [dim]{tool.qualified_name}[/dim]")
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()
        console.print("\n[dim]Connection closed.[/dim]")

    asyncio.run(_test())


@mcp_app.command("catalog")
def mcp_catalog(
    server: str | None = typer.Argument(None, help="Optional configured server name"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass cached MCP catalogs"),
) -> None:
    """Browse MCP prompts and resources with cache freshness."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server and server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)

    async def _catalog() -> None:
        from magent.mcp import MCPManager

        manager = MCPManager(mcp_servers)
        await manager.start_all()
        try:
            prompts = await manager.list_prompts(server, refresh=refresh)
            resources = await manager.list_resources(server, refresh=refresh)

            prompt_table = Table("Server", "Prompt", "Arguments", "Description", title="Prompts")
            for prompt in prompts:
                arguments = ", ".join(
                    str(item.get("name")) for item in prompt.arguments if item.get("name")
                )
                prompt_table.add_row(
                    prompt.server_name,
                    prompt.name,
                    arguments or "-",
                    prompt.description or "-",
                )
            console.print(prompt_table if prompts else "[dim]No prompts advertised.[/dim]")

            resource_table = Table(
                "Server", "Resource", "URI / Template", "Type", title="Resources"
            )
            for resource in resources:
                resource_table.add_row(
                    resource.server_name,
                    resource.name or "-",
                    resource.uri,
                    "template" if resource.template else (resource.mime_type or "resource"),
                )
            console.print(resource_table if resources else "[dim]No resources advertised.[/dim]")

            for name, catalogs in manager.catalog_status().items():
                if server and name != server:
                    continue
                console.print(f"\n[bold]{name} freshness[/bold]")
                for kind, status in catalogs.items():
                    freshness = status.get("freshness") or {}
                    state = "fresh" if freshness.get("fresh") else "stale/unclaimed"
                    ttl = freshness.get("ttl_ms", 0)
                    error = status.get("error")
                    detail = f"{status['count']} items, {state}, ttl={ttl}ms"
                    if error:
                        detail += f", {error}"
                    console.print(f"  {kind}: {detail}", markup=False)
        finally:
            await manager.stop_all()

    asyncio.run(_catalog())


@mcp_app.command("resource")
def mcp_resource(
    server: str = typer.Argument(..., help="Configured MCP server name"),
    uri: str = typer.Argument(..., help="Resource URI"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass the resource cache"),
) -> None:
    """Read one MCP resource in a terminal-friendly format."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)

    async def _resource() -> None:
        from rich.text import Text

        from magent.mcp import MCPManager

        manager = MCPManager({server: mcp_servers[server]})
        await manager.start_all()
        try:
            result = await manager.read_resource(server, uri, refresh=refresh)
            if not result.get("ok"):
                console.print(f"[red]{result.get('error', 'Resource read failed')}[/red]")
                return
            console.print(f"\n[bold]{uri}[/bold]")
            for content in result.get("contents") or []:
                if not isinstance(content, dict):
                    continue
                mime = content.get("mime_type") or content.get("mimeType") or "unknown"
                console.print(f"[dim]{mime}[/dim]")
                if isinstance(content.get("text"), str):
                    console.print(Text(content["text"]))
                elif isinstance(content.get("blob"), str):
                    console.print(
                        f"[dim]Binary resource: {len(content['blob'])} base64 characters[/dim]"
                    )
            if result.get("truncated"):
                console.print("[yellow]Resource output was truncated at the safety limit.[/yellow]")
            cache = result.get("cache") or {}
            console.print(
                f"[dim]cache={cache.get('cache_scope', 'private')} "
                f"ttl={cache.get('ttl_ms', 0)}ms[/dim]"
            )
        finally:
            await manager.stop_all()

    asyncio.run(_resource())


@mcp_app.command("prompt")
def mcp_prompt(
    server: str = typer.Argument(..., help="Configured MCP server name"),
    name: str = typer.Argument(..., help="Prompt name"),
    arguments_json: str = typer.Option("{}", "--arguments", help="Prompt arguments as JSON"),
) -> None:
    """Render one MCP prompt while clearly identifying it as untrusted content."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)
    try:
        raw_arguments = json.loads(arguments_json)
        if not isinstance(raw_arguments, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw_arguments.items()
        ):
            raise ValueError("arguments must be a JSON object with string values")
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(f"[red]Invalid --arguments: {exc}[/red]")
        raise typer.Exit(2) from exc

    async def _prompt() -> None:
        from rich.text import Text

        from magent.mcp import MCPManager

        manager = MCPManager({server: mcp_servers[server]})
        await manager.start_all()
        try:
            result = await manager.get_prompt(server, name, raw_arguments)
            if not result.get("ok"):
                console.print(f"[red]{result.get('error', 'Prompt request failed')}[/red]")
                return
            console.print("[yellow]Untrusted MCP prompt content[/yellow]")
            if result.get("description"):
                console.print(Text(str(result["description"]), style="dim"))
            for message in result.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                console.print(f"\n[bold]{message.get('role', 'message')}[/bold]")
                content = message.get("content") or {}
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    console.print(Text(content["text"]))
                else:
                    console.print_json(data=content)
        finally:
            await manager.stop_all()

    asyncio.run(_prompt())


@mcp_app.command("complete")
def mcp_complete(
    server: str = typer.Argument(..., help="Configured MCP server name"),
    reference: str = typer.Argument(..., help="Prompt name or resource-template URI"),
    name: str = typer.Option(..., "--name", help="Argument name being completed"),
    value: str = typer.Option("", "--value", help="Partial argument value"),
    resource: bool = typer.Option(False, "--resource", help="Complete a resource template"),
    context_json: str = typer.Option("{}", "--context", help="Other arguments as JSON"),
) -> None:
    """Complete a prompt or resource-template argument through MCP."""
    username = get_current_user()
    if not username:
        console.print("[red]No active user.[/red]")
        raise typer.Exit(1)
    cfg = load_config(username)
    mcp_servers = cfg.get("mcp", "servers", default={}) or {}
    if server not in mcp_servers:
        console.print(f"[red]Server '{server}' not found in config.[/red]")
        raise typer.Exit(1)
    try:
        context = json.loads(context_json)
        if not isinstance(context, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in context.items()
        ):
            raise ValueError("context must be a JSON object with string values")
    except (json.JSONDecodeError, ValueError) as exc:
        console.print(f"[red]Invalid --context: {exc}[/red]")
        raise typer.Exit(2) from exc

    async def _complete() -> None:
        from magent.mcp import MCPManager

        manager = MCPManager({server: mcp_servers[server]})
        await manager.start_all()
        try:
            result = await manager.complete(
                server,
                reference,
                {"name": name, "value": value},
                reference_type="resource" if resource else "prompt",
                context_arguments=context,
            )
            if not result.get("ok"):
                console.print(f"[red]{result.get('error', 'Completion failed')}[/red]")
                return
            completion = result.get("completion") or {}
            values = completion.get("values") or []
            for item in values:
                console.print(str(item), markup=False, highlight=False)
            if not values:
                console.print("[dim]No completions returned.[/dim]")
            if completion.get("has_more") or completion.get("hasMore"):
                console.print("[dim]The server has additional completions.[/dim]")
        finally:
            await manager.stop_all()

    asyncio.run(_complete())


@mcp_app.command("init")
def mcp_init() -> None:
    """Print an example MCP config block for config.toml."""
    console.print("\n[bold]Example MCP configuration:[/bold]")
    console.print(EXAMPLE_MCP_CONFIG, markup=False, highlight=False)
    console.print(f"[dim]Config: {CONFIG_DIR / 'config.toml'}[/dim]")
    console.print("[dim]Browse servers: https://github.com/modelcontextprotocol/servers[/dim]\n")
