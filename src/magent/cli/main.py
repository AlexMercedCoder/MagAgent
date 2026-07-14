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
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from magent import __version__
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
    followup_app,
    gateway_app,
    github_app,
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
    known_command_names,
    require_user,
    store,
)
from magent.cli.commands.agents import register_agent_commands
from magent.cli.commands.config import register_config_commands
from magent.cli.commands.daemon import register_daemon_commands
from magent.cli.commands.events import register_event_commands
from magent.cli.commands.hooks import register_hook_commands
from magent.cli.commands.lsp import register_lsp_commands
from magent.cli.commands.performance import register_performance_commands
from magent.cli.commands.permissions import register_permission_commands
from magent.cli.commands.plugins import register_plugin_commands
from magent.cli.commands.providers import register_provider_ux_commands
from magent.cli.commands.workbench import register_workbench_commands
from magent.config import (
    CONFIG_DIR,
    create_user,
    delete_user,
    get_current_user,
    list_users,
    load_config,
    set_current_user,
    user_exists,
    user_memory_dir,
)
from magent.prompt_input import read_multiline_prompt, read_user_prompt

console = Console()
register_agent_commands(agent_app)
register_provider_ux_commands(provider_app)
register_config_commands(config_app)
register_daemon_commands(daemon_app)
register_event_commands(events_app)
register_hook_commands(hook_app)
register_lsp_commands(lsp_app)
register_permission_commands(permission_app)
register_performance_commands(performance_app)
register_plugin_commands(plugin_app)
register_workbench_commands(workbench_app)


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

    main_provider = _build_provider(config, provider, model)
    extract_provider = _build_extraction_provider(config)

    if task:
        _run_one_shot(username, config, main_provider, extract_provider, cwd, task)
    else:
        _run_repl(username, config, main_provider, extract_provider, cwd)


@app.command("ask", rich_help_panel="Everyday Agent Work")
def ask_cmd(
    task: str = typer.Argument(..., help="One-shot task to run non-interactively"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="Provider ID"),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name"),
    project: str | None = typer.Option(None, "--project", help="Project directory"),
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
):
    """Run a one-shot MagAgent task."""
    username = _require_user()
    config = load_config(username)
    permission_override = permission_mode
    if yes:
        permission_override = "yolo"
    cwd = project or os.getcwd()
    main_provider = _build_provider(config, provider, model)
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
):
    """Run a single non-interactive agent task."""
    from magent.agent import AgentSession
    from magent.tui import print_response

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
        interactive_permissions=False,
        permission_mode_override=permission_mode_override,
    )

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

    response = asyncio.run(_run())
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
    fetch_sources: bool = typer.Option(True, "--fetch/--no-fetch", help="Fetch and excerpt source pages."),
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
            should_write = Confirm.ask("Write this research report to the active directory?", default=False)
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


def _print_research_result(result: dict) -> None:
    if not result.get("ok"):
        console.print(f"[red]Research failed:[/red] {result.get('error', 'unknown error')}")
        return
    from rich.markdown import Markdown

    console.print(Panel.fit(f"[bold]{result.get('topic', 'Research')}[/bold]", title="Research"))
    summary = str(result.get("summary") or "").strip()
    if summary:
        console.print(Markdown(summary))
    sources = result.get("sources") or []
    if sources:
        table = Table("Source", "Title", "URL")
        for index, source in enumerate(sources, start=1):
            table.add_row(
                str(index),
                str(source.get("title") or "Untitled")[:80],
                str(source.get("url") or "")[:100],
            )
        console.print(table)


def _print_session_usage(data: dict) -> None:
    if not data.get("ok"):
        console.print("[dim]No session log found yet.[/dim]")
        return
    table = Table("Metric", "Value")
    for key in ("turns", "tool_calls", "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        table.add_row(key.replace("_", " ").title(), str(data.get(key, 0)))
    table.add_row("Estimated Cost", f"${float(data.get('cost_usd') or 0):.6f}")
    console.print(table)
    slowest = data.get("slowest") or []
    if slowest:
        slow_table = Table("Slow Step", "Duration", "Detail")
        for item in slowest[:5]:
            duration = float(item.get("duration_ms") or 0)
            metadata = item.get("metadata") or {}
            detail = str(metadata.get("description") or metadata.get("path") or metadata.get("tool") or "")[:80]
            slow_table.add_row(str(item.get("name") or ""), f"{duration / 1000:.1f}s", detail)
        console.print(slow_table)


def _print_recent_insights(data: dict) -> None:
    totals = data.get("totals") or {}
    console.print(
        Panel(
            "\n".join(
                [
                    f"Sessions: {totals.get('sessions', 0)}",
                    f"Turns: {totals.get('turns', 0)}",
                    f"Tool calls: {totals.get('tool_calls', 0)}",
                    f"Tokens: {totals.get('total_tokens', 0)}",
                    f"Cached tokens: {totals.get('cached_tokens', 0)}",
                    f"Estimated cost: ${float(totals.get('cost_usd') or 0):.6f}",
                ]
            ),
            title="Recent Session Insights",
        )
    )
    rows = data.get("sessions") or []
    if rows:
        table = Table("Session Log", "Turns", "Tools", "Tokens", "Slowest")
        for item in rows:
            slowest = (item.get("slowest") or [{}])[0]
            table.add_row(
                Path(str(item.get("path") or "")).name,
                str(item.get("turns", 0)),
                str(item.get("tool_calls", 0)),
                str(item.get("total_tokens", 0)),
                str(slowest.get("name") or ""),
            )
        console.print(table)


def _write_research_report(result: dict, *, out: str | None = None) -> Path:
    path = Path(out).expanduser() if out else Path.cwd() / f"{_slugify_filename(str(result.get('topic') or 'research'))}.md"
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


def _run_repl(username, config, main_provider, extract_provider, cwd):
    """Run the interactive REPL with streaming output."""
    from magent.agent import AgentSession
    from magent.tui import print_banner, print_streaming_response

    print_banner(username, main_provider.display_name, cwd, config.permission_mode, version=__version__)

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
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
            with contextlib.suppress(Exception):
                loop.run_until_complete(session.cancel_active_work())
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    try:
        console.print("\n[dim]Writing session memories...[/dim]")
        _shutdown()
        console.print("[dim green]Session ended. Goodbye![/dim green]")
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
                "  [cyan]/context [q][/cyan]     — Audit active context and memory\n"
                "  [cyan]/config[/cyan]          — Show config control-center summary\n"
                "  [cyan]/statusline[/cyan]      — Preview statusline payload\n"
                "  [cyan]/usage[/cyan]           — Show token/tool/timing usage for this session\n"
                "  [cyan]/insights[/cyan]        — Show recent session diagnostics\n"
                "  [cyan]/memory[/cyan]          — Show memory stats\n"
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

        data = statusline_data(config, username=get_current_user() or "user", cwd=os.getcwd(), store=_store())
        console.print(render_statusline(data))
        return True

    if command == "/usage":
        from magent.session_controls import session_usage

        _print_session_usage(session_usage(session.logger.path))
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
        modes = ("silent", "balanced", "paranoid", "yolo")
        if arg in modes:
            session.config._user.setdefault("permissions", {})["mode"] = arg
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
            console.print("[yellow]Usage: /spawn <task description>[/yellow]")
            return True
        import uuid as _uuid

        task_id = f"sub_{_uuid.uuid4().hex[:6]}"
        console.print(f"[dim]Spawning sub-agent [{task_id}]...[/dim]")
        result = _loop.run_until_complete(session.spawn_subagent(task_id, arg))
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
        table.add_row(item.get("name", ""), item.get("root", ""), ", ".join(item.get("commands", [])))
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
    """Guided project bootstrap alias for project init."""
    project_init_cmd(path=path, force=force)


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
        table.add_row(item["id"], item.get("status", ""), item.get("source", ""), item.get("text", "")[:100])
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
def routine_add_cmd(name: str = typer.Argument(...), prompt: str = typer.Argument(...), schedule: str = typer.Option("", "--schedule")):
    """Register a recurring routine prompt."""
    item = _store().append("routines", {"name": name, "prompt": prompt, "schedule": schedule})
    console.print(f"[green]✓ Added routine {item['id']}[/green]")


@routine_app.command("list")
def routine_list_cmd():
    """List routines."""
    table = Table("ID", "Name", "Schedule", "Prompt")
    for item in _store().read("routines", []):
        table.add_row(item["id"], item.get("name", ""), item.get("schedule", ""), item.get("prompt", "")[:80])
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
        table.add_row(item["id"], item.get("when", ""), item.get("status", ""), item.get("text", "")[:100])
    console.print(table)


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
    no_diff: bool = typer.Option(False, "--no-diff", help="Do not capture the current diff for executable plans."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable plan data."),
):
    """Generate a local plan without modifying files."""
    from magent.workbench import build_plan, save_execution_plan, save_plan

    text = build_plan(project, goal)
    item = None
    if save:
        if executable:
            item = save_execution_plan(
                _store(),
                project,
                goal,
                commands=command or [],
                include_diff=not no_diff,
            )
        else:
            item = save_plan(_store(), project, goal)
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
        table.add_row(item["id"], item.get("status", ""), item.get("project", ""), item.get("goal", "")[:90])
    console.print(table)


@app.command("plan-apply", rich_help_panel="Planning, Review & Release")
def plan_apply_cmd(
    plan_id: str = typer.Argument(...),
    run_checks: bool = typer.Option(False, "--run-checks"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    sandbox: str | None = typer.Option(None, "--sandbox", help="Run in worktree, copy, or container sandbox"),
    keep_sandbox: bool = typer.Option(False, "--keep-sandbox"),
    image: str = typer.Option("python:3.12", "--image", help="Container image for --sandbox container"),
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
            confirm = Prompt.ask(f"Run plan '{plan_id}' in {sandbox} sandbox?", choices=["y", "n"], default="n")
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
):
    """Run or preview a saved plan in an isolated sandbox."""
    from magent.sandbox import execute_plan_sandbox, sandbox_plan_preview

    if dry_run:
        console.print_json(data=sandbox_plan_preview(_store(), plan_id, mode=mode))
        return
    console.print_json(data=execute_plan_sandbox(_store(), plan_id, mode=mode, run_checks=run_checks, keep=keep, image=image))


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
def plan_run_cmd(goal: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
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
def plan_discard_cmd(plan_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")):
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
    plan_cmd(goal, project or os.getcwd())


@app.command("goal", rich_help_panel="Everyday Agent Work")
def goal_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    background: bool = typer.Option(False, "--background/--no-background", help="Queue the goal as a daemon task."),
    run: bool = typer.Option(False, "--run/--no-run", help="Run the generated goal prompt immediately."),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="Include verifier pass instructions."),
    review: bool = typer.Option(True, "--review/--no-review", help="Include reviewer pass instructions."),
    max_loops: int = typer.Option(3, "--max-loops", min=1, max=20),
    verifier_model: str = typer.Option("cheap", "--verifier-model-role"),
    reviewer_model: str = typer.Option("review", "--reviewer-model-role"),
    provider: str | None = typer.Option(None, "--provider", help="Provider ID when using --run."),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name when using --run."),
    permission_mode: str | None = typer.Option(None, "--permission-mode", help="Permission mode when using --run."),
    repair_attempts: int = typer.Option(2, "--repair-attempts", min=0, max=5, help="Audit repair attempts when using --run."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create a goal loop with verifier/reviewer workflow scaffolding."""
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
        console.print("[dim]Inspect with `magent jobs` and run due work with `magent daemon run-once`.[/dim]")
    elif run:
        username = _require_user()
        cfg = load_config(username)
        main_provider = _build_provider(cfg, provider, model)
        extract_provider = _build_extraction_provider(cfg)
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
        )
    else:
        console.print("[dim]Run now with:[/dim]")
        console.print(f"  magent goal {json.dumps(goal)} --project {json.dumps(str(Path(project).resolve()))} --run")
        console.print("[dim]Or run the generated prompt directly:[/dim]")
        console.print(f"  magent ask {json.dumps(goal_item['prompt'])} --project {json.dumps(str(Path(project).resolve()))} --repair-attempts 2 --strict-audit")


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


@app.command("statusline", rich_help_panel="Setup & Configuration")
def statusline_cmd(
    template: str = typer.Option("", "--template", "-t", help="Python format template for statusline fields."),
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
    fail_on: str | None = typer.Option(None, "--fail-on", help="Exit non-zero if findings at or above priority exist"),
):
    """Review the local git diff for common risks."""
    from magent.workbench import review_diff, review_fails_threshold, review_summary, save_review

    if save:
        item = save_review(_store(), project, base)
        console.print(f"[green]✓ Saved review {item['id']}[/green]")
        if json_out:
            console.print_json(data=item)
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


@app.command("graph", rich_help_panel="Memory & Context")
def graph_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Show a lightweight repository import graph."""
    from magent.workbench import repo_graph

    console.print_json(data=repo_graph(project))


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
    console.print_json(data={"root": index["root"], "files": len(index["files"]), "symbols": len(index["symbols"])})


@code_app.command("symbols")
def code_symbols_cmd(query: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
    """Search indexed code symbols."""
    from magent.workbench import search_symbols

    table = Table("Kind", "Name", "Path", "Line")
    for item in search_symbols(_store(), query, project):
        table.add_row(item.get("kind", ""), item.get("name", ""), item.get("path", ""), str(item.get("line", "")))
    console.print(table)


@code_app.command("related")
def code_related_cmd(file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
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
def test_related_cmd(file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
    """Show tests related to a source file."""
    from magent.workbench import related_tests

    for test in related_tests(project, file):
        console.print(test)


@test_app.command("explain")
def test_explain_cmd(file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
    """Explain why tests are related to a source file."""
    from magent.workbench import explain_related_tests

    console.print_json(data=explain_related_tests(project, file))


@test_app.command("run-related")
def test_run_related_cmd(file: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
    """Run tests related to a source file."""
    from magent.workbench import run_related_tests

    console.print_json(data=run_related_tests(project, file))


@patch_app.command("save")
def patch_save_cmd(name: str = typer.Option("", "--name"), project: str = typer.Option(".", "--project", "-p")):
    """Save the current git diff to the patch queue."""
    from magent.workbench import save_patch

    item = save_patch(_store(), project, name)
    console.print(f"[green]✓ Saved {item['id']}[/green] {item['path']}")


@patch_app.command("list")
def patch_list_cmd():
    """List saved patches."""
    table = Table("ID", "Name", "Bytes", "Path")
    for item in _store().read("patches", []):
        table.add_row(item["id"], item.get("name", ""), str(item.get("bytes", 0)), item.get("path", ""))
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
def patch_apply_cmd(patch_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")):
    """Apply a saved patch after git apply --check passes."""
    from magent.workbench import apply_saved_patch

    if not yes:
        confirm = Prompt.ask(f"Apply patch '{patch_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=apply_saved_patch(_store(), patch_id))


@patch_app.command("revert")
def patch_revert_cmd(patch_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")):
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


@context_app.command("map")
def context_map_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    query: str = typer.Option("", "--query", "-q"),
    json_output: bool = typer.Option(False, "--json", help="Emit the full machine-readable context payload."),
):
    """Show memory, workbench, and project state for the current project."""
    from magent.context import context_map

    mgr, _ = _get_memory_manager()
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

    mgr, _ = _get_memory_manager()
    data = context_audit(context_map(_store(), project=project, memory_manager=mgr, query=query))
    if json_output:
        console.print_json(data=data)
        return
    _print_context_map(data["data"])
    console.print("[bold]Context Hygiene Suggestions[/bold]")
    for item in data.get("suggestions", []):
        console.print(f"- {item}")


def _print_context_map(data: dict) -> None:
    console.print(Panel.fit(f"[bold]{data.get('project', '')}[/bold]", title="Context Map"))
    workspace = data.get("workspace") or {}
    doctor = data.get("project_doctor") or {}
    memory = data.get("memory") or {}
    table = Table("Area", "Signal")
    table.add_row("Git", f"{len(workspace.get('git_status') or [])} status entries")
    table.add_row("Plans", str(workspace.get("pending_plans", 0)))
    table.add_row("Patches", str(workspace.get("patches", 0)))
    table.add_row("Checkpoints", str(workspace.get("checkpoint_sessions", 0)))
    missing = doctor.get("missing") or []
    table.add_row("Project doctor", "ok" if doctor.get("ok") else f"missing: {', '.join(missing[:4]) or 'none'}")
    stats = memory.get("stats") or {}
    table.add_row("Memory", f"{stats.get('nodes', 0)} nodes" if memory.get("available") else "unavailable")
    console.print(table)

    plans = (data.get("active_workbench") or {}).get("plans") or []
    if plans:
        plan_table = Table("ID", "Status", "Mode", "Goal")
        for plan in plans[:5]:
            plan_table.add_row(
                plan.get("id", ""),
                plan.get("status", ""),
                plan.get("mode", "draft"),
                str(plan.get("goal", ""))[:80],
            )
        console.print(plan_table)

    candidates = data.get("promotion_candidates") or []
    if candidates:
        cand_table = Table("Memory Candidate", "Source", "Title")
        for item in candidates[:8]:
            cand_table.add_row(
                item.get("id", ""),
                item.get("source", ""),
                str(item.get("title", ""))[:80],
            )
        console.print(cand_table)
    else:
        console.print("[dim]No high-value memory promotion candidates right now.[/dim]")

    recall = (memory.get("recall") or "").strip()
    if recall:
        console.print(Panel(recall, title="Memory Recall"))


def _print_jobs_summary(data: dict) -> None:
    counts = data.get("counts") or {}
    title = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items())) or "no jobs"
    console.print(Panel.fit(title, title="Background Jobs"))
    table = Table("ID", "Status", "Kind", "Project", "Payload")
    for item in (data.get("jobs") or [])[:20]:
        payload = item.get("payload") or {}
        table.add_row(
            item.get("id", ""),
            item.get("status", ""),
            item.get("kind", ""),
            Path(item.get("project", ".")).name,
            json.dumps(payload)[:90],
        )
    console.print(table)


def _print_config_center(config, provider_display: str = "") -> None:
    console.print(Panel.fit("[bold]MagAgent Config[/bold]", title="Control Center"))
    table = Table("Area", "Current", "Command")
    table.add_row(
        "Provider",
        f"{config.default_provider}/{config.default_model}",
        "magent provider wizard",
    )
    table.add_row(
        "Model roles",
        ", ".join(f"{role}:{value or '-'}" for role, value in config.model_roles.items()),
        "magent model wizard",
    )
    table.add_row("Permissions", config.permission_mode, "magent permission set <mode>")
    table.add_row(
        "Memory",
        f"write every {config.write_every_n_turns} turns",
        "magent memory configure",
    )
    table.add_row(
        "Subagents",
        f"max {config.max_subagents}, parallel {config.max_parallel_subagents}",
        "magent subagent wizard",
    )
    table.add_row("Tools", "capability packs", "magent tools list")
    table.add_row("Context", "audit active context", "magent context audit")
    if provider_display:
        table.add_row("Session provider", provider_display, "magent model")
    console.print(table)


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
def recipe_show_cmd(name: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
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
    step: Annotated[list[str] | None, typer.Option("--step", help="Recipe step; may be repeated")] = None,
    command: Annotated[
        list[str] | None,
        typer.Option("--command", "-c", help="Command; may be repeated"),
    ] = None,
):
    """Save a reusable workflow recipe."""
    from magent.recipes import save_recipe

    console.print_json(data=save_recipe(_store(), name, description=description, steps=step or [], commands=command or []))


@recipe_app.command("run")
def recipe_run_cmd(name: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
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
            "sandbox": execute_plan_sandbox(_store(), plan_id, mode=mode, run_checks=run_checks, keep=keep, image=image),
        }
    )


@tools_app.command("list")
def tools_list_cmd():
    """List tool capability packs and enabled state."""
    from magent.tool_packs import list_packs

    console.print_json(data={"ok": True, "packs": list_packs(_store())})


@tools_app.command("explain")
def tools_explain_cmd(pack: str = typer.Argument(...)):
    """Explain a tool capability pack."""
    from magent.tool_packs import explain_pack

    result = explain_pack(pack, _store())
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@tools_app.command("enable")
def tools_enable_cmd(pack: str = typer.Argument(...)):
    """Enable a tool capability pack."""
    from magent.tool_packs import set_pack_enabled

    result = set_pack_enabled(_store(), pack, True)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@tools_app.command("disable")
def tools_disable_cmd(pack: str = typer.Argument(...)):
    """Disable a tool capability pack."""
    from magent.tool_packs import set_pack_enabled

    result = set_pack_enabled(_store(), pack, False)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@tools_app.command("gateway")
def tools_gateway_cmd():
    """Show local, subscription, and MCP tool backend readiness."""
    from magent.tool_gateway import gateway_status

    config = load_config(_require_user())
    data = gateway_status(config)
    table = Table("Backend", "Enabled", "Credential", "Description")
    for item in data.get("backends", []):
        table.add_row(
            item.get("id", ""),
            "yes" if item.get("enabled") else "no",
            item.get("credential") or "-",
            item.get("description", "")[:90],
        )
    console.print(table)


@tools_app.command("backend")
def tools_backend_cmd(name: str = typer.Argument(...)):
    """Explain one tool backend/gateway surface."""
    from magent.tool_gateway import explain_backend

    result = explain_backend(name)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


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
def skill_search_cmd(query: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
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
def skill_show_cmd(name: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
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
    access_mode: str = typer.Option("", "--access", help="api, codex, payg, subscription, or local"),
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
        )
    )


@provider_app.command("wizard")
def provider_wizard_cmd():
    """Interactively configure provider, access mode, model, and key source."""
    from magent.config_ux import provider_access_modes, provider_choices, set_default_provider
    from magent.provider_catalog import provider_env_vars

    choices = provider_choices()
    for i, item in enumerate(choices, 1):
        console.print(f"{i}. {item['id']} — {item['label']}")
    choice = Prompt.ask("Provider number", default="1")
    try:
        selected = choices[int(choice) - 1]
    except (ValueError, IndexError):
        selected = choices[0]
    modes = provider_access_modes(selected["id"])
    for i, item in enumerate(modes, 1):
        console.print(f"{i}. {item['id']} — {item['label']}")
    access_choice = Prompt.ask("Access mode", default="1")
    try:
        access_mode = modes[int(access_choice) - 1]["id"]
    except (ValueError, IndexError):
        access_mode = modes[0]["id"]
    model = Prompt.ask("Default model", default=selected["default_model"])
    api_key_env = ""
    api_key = ""
    if access_mode not in {"codex", "local"}:
        default_env = provider_env_vars().get(selected["id"], "")
        console.print("[dim]Choose how MagAgent should find this provider credential.[/dim]")
        console.print("  [cyan]1[/cyan]. Paste key now and save it in MagAgent config")
        console.print(f"  [cyan]2[/cyan]. Use environment variable [bold]{default_env}[/bold]")
        console.print("  [cyan]3[/cyan]. Skip for now")
        credential_choice = Prompt.ask("Credential option", choices=["1", "2", "3"], default="1")
        if credential_choice == "1":
            api_key = Prompt.ask("API key", password=True, default="").strip()
            if not api_key:
                console.print("[yellow]No key entered; falling back to environment variable setup.[/yellow]")
                api_key_env = Prompt.ask("API key environment variable", default=default_env)
        elif credential_choice == "2":
            api_key_env = Prompt.ask("API key environment variable", default=default_env)
        else:
            console.print(
                f"[yellow]Skipping credential. You can add one later with "
                f"[bold]magent provider wizard[/bold] or [bold]magent provider set {selected['id']} --api-key-env {default_env}[/bold].[/yellow]"
            )
    result = set_default_provider(
        selected["id"],
        model,
        api_key_env=api_key_env,
        api_key=api_key,
        access_mode=access_mode,
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

    console.print_json(data={"ok": True, "model_roles": ux_doctor(get_current_user())["model_roles"]})


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
    """Interactively set common model roles from the current default model."""
    from magent.config_ux import MODEL_ROLES, set_model_role

    config = load_config(get_current_user())
    default = f"{config.default_provider}/{config.default_model}"
    results = []
    for role in MODEL_ROLES:
        value = Prompt.ask(f"{role} model", default=default if role != "fallback" else "")
        if value:
            results.append(set_model_role(role, value))
    console.print_json(data={"ok": all(item.get("ok") for item in results), "results": results})


@model_app.command("image-wizard")
def model_image_wizard_cmd():
    """Interactively configure the image_maker model role and credentials."""
    from magent.config_ux import (
        configure_provider_entry,
        image_model_choices,
        set_model_role,
    )
    from magent.provider_catalog import provider_env_vars

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
    console.print(f"  [cyan]2[/cyan]. Use environment variable [bold]{default_env or 'PROVIDER_API_KEY'}[/bold]")
    console.print("  [cyan]3[/cyan]. Skip credential setup")
    credential_choice = Prompt.ask("Credential option", choices=["1", "2", "3"], default="2")
    if credential_choice == "1":
        api_key = Prompt.ask("API key", password=True, default="").strip()
        if not api_key:
            console.print("[yellow]No key entered; falling back to environment variable setup.[/yellow]")
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
    entry = cfg.setdefault("providers", {}).setdefault(provider_id, {})
    entry.pop("api_key_keyring", None)
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


@config_app.command("schema")
def config_schema_cmd():
    """Show generated config schema/default field metadata."""
    from magent.config_validation import config_schema

    console.print_json(data=config_schema())


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
    """Interactively configure sub-agent caps."""
    from magent.config_ux import configure_subagents

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


@eval_app.command("init")
def eval_init_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Create a starter local eval suite."""
    from magent.evals import init_evals

    console.print_json(data=init_evals(project))


@eval_app.command("list")
def eval_list_cmd(project: str = typer.Option(".", "--project", "-p")):
    """List local eval suites."""
    from magent.evals import list_eval_suites

    console.print_json(data={"ok": True, "suites": list_eval_suites(project)})


@eval_app.command("run")
def eval_run_cmd(
    suite: str = typer.Argument("evals/magagent-evals.json"),
    project: str = typer.Option(".", "--project", "-p"),
):
    """Run a local eval suite's verification commands."""
    from magent.evals import run_eval_suite

    console.print_json(data=run_eval_suite(project, suite, store=_store()))


@eval_app.command("report")
def eval_report_cmd(limit: int = typer.Option(20, "--limit", "-n")):
    """Show recent eval run reports."""
    from magent.evals import eval_report

    console.print_json(data={"ok": True, "runs": eval_report(_store(), limit=limit)})


@browser_app.command("snapshot")
def browser_snapshot_cmd(url: str = typer.Argument(...), wait_ms: int = typer.Option(500, "--wait-ms")):
    """Capture title and text from a page using Playwright."""
    from magent.browser import browser_snapshot

    console.print_json(data=asyncio.run(browser_snapshot(url, wait_ms=wait_ms)))


@browser_app.command("screenshot")
def browser_screenshot_cmd(
    url: str = typer.Argument(...),
    out: str = typer.Option("magent-browser.png", "--out", "-o"),
    wait_ms: int = typer.Option(500, "--wait-ms"),
):
    """Capture a page screenshot using Playwright."""
    from magent.browser import browser_screenshot

    console.print_json(data=asyncio.run(browser_screenshot(url, out, wait_ms=wait_ms)))


@github_app.command("status")
def github_status_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Check gh availability and authentication."""
    from magent.github_workflows import github_status

    console.print_json(data=github_status(project))


@github_app.command("issues")
def github_issues_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    limit: int = typer.Option(20, "--limit", "-n"),
    state: str = typer.Option("open", "--state"),
):
    """List GitHub issues with gh."""
    from magent.github_workflows import list_issues

    console.print_json(data=list_issues(project, limit=limit, state=state))


@github_app.command("prs")
def github_prs_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    limit: int = typer.Option(20, "--limit", "-n"),
    state: str = typer.Option("open", "--state"),
):
    """List GitHub pull requests with gh."""
    from magent.github_workflows import list_prs

    console.print_json(data=list_prs(project, limit=limit, state=state))


@github_app.command("issue")
def github_issue_cmd(number: int = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
    """Show one GitHub issue with gh."""
    from magent.github_workflows import show_issue

    console.print_json(data=show_issue(project, number))


@github_app.command("pr")
def github_pr_cmd(number: int = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
    """Show one GitHub pull request with gh."""
    from magent.github_workflows import show_pr

    console.print_json(data=show_pr(project, number))


@github_app.command("checks")
def github_checks_cmd(
    number: int | None = typer.Argument(None),
    project: str = typer.Option(".", "--project", "-p"),
):
    """Show pull request checks with gh."""
    from magent.github_workflows import pr_checks

    console.print_json(data=pr_checks(project, number))


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

    console.print_json(data=ci_triage(project, logs=logs, repair_plan=repair_plan, store=_store(), save=save))


@app.command("diagnostics", rich_help_panel="Performance & Diagnostics")
def diagnostics_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    deep: bool = typer.Option(False, "--deep", help="Include provider, MCP, hooks, plugins, and permissions."),
    prompt: str = typer.Option("", "--prompt", help="Optional prompt to verify expected artifacts from."),
):
    """Run available local diagnostics for the current project."""
    if deep:
        from magent.diagnostics import deep_diagnostics

        username = _require_user()
        console.print_json(data=deep_diagnostics(username, load_config(username), _store(), project=project, prompt=prompt))
        return
    from magent.workbench import project_diagnostics

    console.print_json(data=project_diagnostics(project, store=_store()))


@app.command("docs-brief", rich_help_panel="Help & Learning")
def docs_brief_cmd(project: str = typer.Option(".", "--project", "-p"), out: str | None = typer.Option(None, "--out")):
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
    result = sqlite_query(user or _require_user(), sql, db_name, parsed if isinstance(parsed, list) else [])
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@api_app.command("save")
def api_save_cmd(name: str = typer.Argument(...), method: str = typer.Argument(...), url: str = typer.Argument(...)):
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
        console.print("[dim]Press Ctrl+C to stop.[/dim]")
        try:
            signal.pause()
        except (AttributeError, KeyboardInterrupt):
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
    result = serve_ui(_store(), project=project, username=username, port=port, open_browser=open_browser)
    console.print_json(data=result)
    console.print("[dim]Press Ctrl+C to stop.[/dim]")
    try:
        signal.pause()
    except (AttributeError, KeyboardInterrupt):
        return


@docs_app.command("list")
def docs_list_cmd():
    """List built-in documentation topics."""
    from magent.docs import list_topics

    table = Table("Topic", "Title")
    for topic in list_topics():
        table.add_row(topic.slug, topic.title)
    console.print(table)


@docs_app.command("show")
def docs_show_cmd(topic: str = typer.Argument(...)):
    """Show a built-in documentation topic."""
    from magent.docs import read_topic

    try:
        console.print(read_topic(topic))
    except KeyError:
        console.print(f"[red]Unknown docs topic: {topic}[/red]")
        raise typer.Exit(1) from None


@docs_app.command("search")
def docs_search_cmd(query: str = typer.Argument(...), limit: int = typer.Option(8, "--limit", "-n")):
    """Search built-in MagAgent documentation."""
    from magent.docs import search_docs

    results = search_docs(query, limit=limit)
    table = Table("Topic", "Score", "Snippet")
    for item in results:
        table.add_row(item["slug"], str(item["score"]), item["snippet"])
    console.print(table)


@docs_app.command("doctor")
def docs_doctor_cmd():
    """Check built-in docs coverage."""
    from magent.docs import docs_doctor

    console.print_json(data=docs_doctor(_known_command_names()))


@docs_app.command("generate-reference")
def docs_generate_reference_cmd(
    out: str | None = typer.Option(None, "--out", "-o"),
    check: bool = typer.Option(False, "--check", help="Fail if the generated reference differs from --out."),
):
    """Generate command reference Markdown from the live CLI tree."""
    from magent.docs import render_command_reference

    text = render_command_reference(_known_command_names())
    target = Path(out or "src/magent/docs/command-reference.md")
    if check:
        if not target.exists():
            console.print(f"[red]Command reference is missing: {target}[/red]")
            raise typer.Exit(1)
        if target.read_text(encoding="utf-8", errors="replace") != text:
            console.print(f"[red]Command reference is stale: {target}[/red]")
            console.print(f"[dim]Run: magent docs generate-reference --out {target}[/dim]")
            raise typer.Exit(1)
        console.print(f"[green]✓ Command reference is current: {target}[/green]")
    elif out:
        target.write_text(text, encoding="utf-8")
        console.print(f"[green]✓ Wrote {target}[/green]")
    else:
        console.print(text)


@docs_app.command("generate-providers")
def docs_generate_providers_cmd(out: str | None = typer.Option(None, "--out", "-o")):
    """Generate provider reference Markdown from the provider catalog."""
    from magent.docs import render_provider_reference

    text = render_provider_reference()
    target = out or "src/magent/docs/providers.md"
    Path(target).write_text(text, encoding="utf-8")
    console.print(f"[green]✓ Wrote {target}[/green]")


@docs_app.command("generate-config")
def docs_generate_config_cmd(out: str | None = typer.Option(None, "--out", "-o")):
    """Generate config reference Markdown from packaged defaults."""
    from magent.docs import render_config_reference

    text = render_config_reference()
    target = out or "src/magent/docs/config-reference.md"
    Path(target).write_text(text, encoding="utf-8")
    console.print(f"[green]✓ Wrote {target}[/green]")


@checkpoint_app.command("list")
def checkpoint_list_cmd(limit: int = typer.Option(20, "--limit", "-n")):
    """List recent file checkpoints."""
    from magent.workbench import list_checkpoints

    table = Table("ID", "Operation", "Status", "Path")
    for item in list_checkpoints(_store(), limit=limit):
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
def checkpoint_diff_cmd(checkpoint_id: str = typer.Argument(...)):
    """Show a diff from checkpoint contents to current file contents."""
    from magent.workbench import checkpoint_diff

    result = checkpoint_diff(_store(), checkpoint_id)
    if not result.get("ok"):
        console.print_json(data=result)
        raise typer.Exit(1)
    console.print(result.get("diff") or "[dim]No diff.[/dim]")


@checkpoint_app.command("restore")
def checkpoint_restore_cmd(
    checkpoint_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Restore a checkpoint."""
    from magent.workbench import restore_checkpoint

    if not yes:
        confirm = Prompt.ask(f"Restore checkpoint '{checkpoint_id}'?", choices=["y", "n"], default="n")
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
def checkpoint_session_list_cmd():
    """List checkpoint sessions."""
    from magent.workbench import checkpoint_sessions

    table = Table("Session", "Count", "Last", "Paths")
    for item in checkpoint_sessions(_store()):
        table.add_row(
            item.get("session_id", ""),
            str(item.get("count", 0)),
            item.get("last_at", "")[:19],
            ", ".join(item.get("paths", []))[:120],
        )
    console.print(table)


@checkpoint_app.command("session-diff")
def checkpoint_session_diff_cmd(session_id: str = typer.Argument(...)):
    """Show combined diffs for a checkpoint session."""
    from magent.workbench import checkpoint_session_diff

    result = checkpoint_session_diff(_store(), session_id)
    console.print(result.get("diff") or "[dim]No diff.[/dim]")


@checkpoint_app.command("session-restore")
def checkpoint_session_restore_cmd(
    session_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Restore all checkpoints for a session in reverse order."""
    from magent.workbench import checkpoint_session_restore

    if not yes:
        confirm = Prompt.ask(f"Restore checkpoint session '{session_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=checkpoint_session_restore(_store(), session_id))


@memory_app.command("review")
def memory_review_cmd(diff: bool = typer.Option(False, "--diff")):
    """Show pending git changes in the current user's memory graph."""
    from magent.workbench import memory_pending_summary

    console.print_json(data=memory_pending_summary(_require_user(), include_diff=diff))


@memory_app.command("approve")
def memory_approve_cmd(message: str = typer.Option("Approve MagAgent memory updates", "--message", "-m")):
    """Commit pending memory graph changes for the current user."""
    from magent.workbench import memory_approve

    console.print_json(data=memory_approve(_require_user(), message=message))


@memory_app.command("promote")
def memory_promote_cmd(
    source: str | None = typer.Argument(None),
    source_id: str | None = typer.Argument(None),
    project: str = typer.Option(".", "--project", "-p"),
    all_candidates: bool = typer.Option(False, "--all"),
    limit: int = typer.Option(20, "--limit"),
):
    """Promote workbench facts into durable MagGraph memory."""
    from magent.context import promote_all_candidates, promote_candidate, promotion_candidates

    mgr, _ = _get_memory_manager()
    store = _store()
    if all_candidates:
        console.print_json(data=promote_all_candidates(store, mgr, project=project, limit=limit))
        return
    if source and source_id:
        console.print_json(data=promote_candidate(store, mgr, source, source_id, project=project))
        return
    console.print_json(data={"ok": True, "candidates": promotion_candidates(store, project, limit=limit)})


@memory_app.command("inbox")
def memory_inbox_cmd(
    action: str = typer.Argument("list", help="list, accept, reject, or edit"),
    candidate_id: str | None = typer.Argument(None),
    project: str = typer.Option(".", "--project", "-p"),
    limit: int = typer.Option(30, "--limit", "-n"),
    reason: str = typer.Option("", "--reason"),
    title: str = typer.Option("", "--title"),
    body: str = typer.Option("", "--body"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Emit JSON output."),
):
    """Review, accept, reject, or edit pending memory candidates."""
    from magent.memory_inbox import accept_candidate, edit_candidate, memory_inbox, reject_candidate

    store = _store()
    normalized = action.lower()
    if normalized == "list":
        data = memory_inbox(store, project=project, limit=limit)
        if json_output:
            console.print_json(data=data)
        else:
            for item in data.get("candidates", []):
                console.print(f"{item.get('id', '')}\t{item.get('status', 'pending')}\t{item.get('title', '')}")
        return
    if not candidate_id:
        console.print_json(data={"ok": False, "error": "candidate_id is required"})
        raise typer.Exit(1)
    if normalized == "accept":
        mgr, _ = _get_memory_manager()
        console.print_json(data=accept_candidate(store, mgr, candidate_id, project=project))
        return
    if normalized == "reject":
        console.print_json(data=reject_candidate(store, candidate_id, reason=reason))
        return
    if normalized == "edit":
        if not body:
            console.print_json(data={"ok": False, "error": "--body is required for edit"})
            raise typer.Exit(1)
        console.print_json(data=edit_candidate(store, candidate_id, body=body, title=title))
        return
    console.print_json(data={"ok": False, "error": f"Unknown inbox action: {action}"})
    raise typer.Exit(1)


@memory_app.command("quality")
def memory_quality_cmd():
    """Report duplicate or suppressed memory nodes."""
    mgr, _ = _get_memory_manager()
    console.print_json(data=mgr.quality_report())


@memory_app.command("merge")
def memory_merge_cmd(
    target_id: str = typer.Argument(...),
    source_id: str = typer.Argument(...),
    preview: bool = typer.Option(False, "--preview"),
):
    """Merge source memory node into target and delete source."""
    mgr, _ = _get_memory_manager()
    data = mgr.merge_preview(target_id, source_id) if preview else mgr.merge_nodes(target_id, source_id)
    console.print_json(data=data)


@memory_app.command("suppress")
def memory_suppress_cmd(
    node_id: str = typer.Argument(...),
    reason: str = typer.Option("", "--reason", "-r"),
):
    """Mark a memory node as suppressed."""
    mgr, _ = _get_memory_manager()
    console.print_json(data=mgr.suppress_node(node_id, reason=reason))


@memory_app.command("unsuppress")
def memory_unsuppress_cmd(node_id: str = typer.Argument(...)):
    """Remove suppressed markers from a memory node."""
    mgr, _ = _get_memory_manager()
    console.print_json(data=mgr.unsuppress_node(node_id))


# ─────────────────────────────────────────────
# User subcommands
# ─────────────────────────────────────────────


@user_app.command("create")
def user_create(name: str = typer.Argument(..., help="Username to create")):
    """Create a new user profile."""
    if user_exists(name):
        console.print(f"[yellow]User '{name}' already exists.[/yellow]")
        raise typer.Exit(1)
    create_user(name)
    console.print(f"[green]✓ Created user [bold]{name}[/bold][/green]")
    if not get_current_user():
        set_current_user(name)
        console.print(f"[dim]Switched to user: {name}[/dim]")


@user_app.command("switch")
def user_switch(name: str = typer.Argument(..., help="Username to switch to")):
    """Switch the active user."""
    if not user_exists(name):
        console.print(f"[red]User '{name}' does not exist.[/red]")
        raise typer.Exit(1)
    set_current_user(name)
    console.print(f"[green]✓ Switched to user [bold]{name}[/bold][/green]")


@user_app.command("delete")
def user_delete(
    name: str = typer.Argument(..., help="Username to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a user and their memory graph."""
    if not user_exists(name):
        console.print(f"[red]User '{name}' does not exist.[/red]")
        raise typer.Exit(1)
    if not yes:
        confirm = Prompt.ask(
            f"[red]Delete user '{name}' and ALL their memory? Type 'yes' to confirm[/red]",
            default="no",
        )
        if confirm.lower() != "yes":
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()
    delete_user(name)
    console.print(f"[green]✓ Deleted user [bold]{name}[/bold][/green]")


@user_app.command("list")
def user_list():
    """List all user profiles."""
    users = list_users()
    current = get_current_user()
    if not users:
        console.print("[dim]No users found. Run [bold]magent setup[/bold] to get started.[/dim]")
        return
    t = Table("User", "Status")
    for u in users:
        marker = "[bold green]● active[/bold green]" if u == current else "[dim]○[/dim]"
        t.add_row(u, marker)
    console.print(t)


@user_app.command("current")
def user_current():
    """Show the currently active user."""
    user = get_current_user()
    if user:
        console.print(f"[bold]{user}[/bold]")
    else:
        console.print("[dim]No active user.[/dim]")


# ─────────────────────────────────────────────
# Memory subcommands
# ─────────────────────────────────────────────


def _get_memory_manager():
    username = _require_user()
    memory_dir = user_memory_dir(username)
    config = load_config(username)
    from magent.memory import MemoryManager

    return (
        MemoryManager(
            memory_dir,
            budget_tokens=config.memory_budget_tokens,
            max_node_tokens=config.recall_body_tokens,
            username=username,
            semantic_enabled=config.semantic_memory_enabled,
            semantic_provider=config.semantic_memory_provider,
            semantic_model=config.semantic_memory_model,
        ),
        username,
    )


@memory_app.command("stats")
def memory_stats(
    user: str | None = typer.Option(None, "--user", "-u", help="Target user (default: current)"),
):
    """Show memory graph statistics."""
    username = user or _require_user()
    if not user_exists(username):
        console.print(f"[red]User '{username}' not found.[/red]")
        raise typer.Exit(1)
    memory_dir = user_memory_dir(username)
    from magent.memory import MemoryManager

    mgr = MemoryManager(memory_dir)
    stats = mgr.stats()
    _print_memory_stats(stats, username)


def _print_memory_stats(stats: dict, username: str):
    from magent.utils import human_bytes

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Key", style="dim")
    t.add_column("Value", style="bold")

    t.add_row("Nodes", str(stats.get("nodes", 0)))
    t.add_row("Edges", str(stats.get("edges_total", 0)))

    nt = stats.get("node_types", {})
    for ntype, count in sorted(nt.items(), key=lambda x: -x[1]):
        t.add_row(f"  {ntype}", str(count))

    t.add_row("", "")
    t.add_row("Graph disk", human_bytes(stats.get("disk_bytes", 0)))
    t.add_row("Avg node size", human_bytes(stats.get("avg_node_bytes", 0)))
    t.add_row("Largest node", human_bytes(stats.get("largest_node_bytes", 0)))
    t.add_row("Git commits", str(stats.get("git_commits", "n/a")))
    t.add_row("Last modified", str(stats.get("last_modified", "n/a")))

    console.print(Panel(t, title=f"[bold cyan]Memory Graph — {username}[/bold cyan]"))


@memory_app.command("graph")
def memory_graph_cmd(
    query: str = typer.Option("", "--query", "-q", help="Optional graph search query."),
    limit: int = typer.Option(100, "--limit", "-n"),
    user: str | None = typer.Option(None, "--user", "-u"),
):
    """Return a compact JSON memory graph view for desktop integrations."""
    from magent.desktop_api import memory_graph

    console.print_json(data=memory_graph(user or _require_user(), query=query, limit=limit))


@memory_app.command("node")
def memory_node_cmd(
    node_id: str = typer.Argument(...),
    user: str | None = typer.Option(None, "--user", "-u"),
):
    """Return one memory node as JSON with nearby traversal context."""
    from magent.desktop_api import memory_node

    result = memory_node(user or _require_user(), node_id)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@memory_app.command("update-node")
def memory_update_node_cmd(
    node_id: str = typer.Argument(...),
    body: str = typer.Option("", "--body", help="Replacement Markdown body."),
    body_file: str = typer.Option("", "--body-file", help="Read replacement Markdown body from a file."),
    links_json: str = typer.Option("", "--links-json", help="Optional JSON array of links to preserve/add."),
    preview: bool = typer.Option(False, "--preview", help="Preview hashes and size changes without writing."),
    user: str | None = typer.Option(None, "--user", "-u"),
):
    """Update a memory node body for desktop integrations."""
    from pathlib import Path

    from magent.desktop_api import memory_update_node, parse_json_value

    resolved_body: str | None = body if body else None
    if body_file:
        resolved_body = Path(body_file).read_text(encoding="utf-8")
    links = parse_json_value(links_json) if links_json else None
    if links is not None and not isinstance(links, list):
        console.print_json(data={"ok": False, "error": "--links-json must be a JSON array"})
        raise typer.Exit(1)
    result = memory_update_node(
        user or _require_user(),
        node_id,
        body=resolved_body,
        links=links,
        preview=preview,
    )
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n"),
    mode: str = typer.Option("hybrid", "--mode", help="keyword, semantic, or hybrid"),
    keyword: bool = typer.Option(False, "--keyword", help="Force keyword search"),
    semantic: bool = typer.Option(False, "--semantic", help="Force semantic search"),
):
    """Search the memory graph."""
    mgr, username = _get_memory_manager()
    if keyword:
        mode = "keyword"
    if semantic:
        mode = "semantic"
    results = mgr.search(query, max_results=limit, mode=mode)
    if not results:
        console.print(f"[dim]No results for '{query}'[/dim]")
        return
    t = Table("ID", "Type", "Score", "Snippet")
    for r in results:
        t.add_row(
            r["id"],
            r.get("type", "?"),
            str(r.get("score", "")),
            r.get("snippet", "")[:90],
        )
    console.print(t)


@memory_app.command("index")
def memory_index_cmd():
    """Build or update the semantic memory search index."""
    mgr, _ = _get_memory_manager()
    with console.status("[bold]Indexing semantic memory...[/bold]"):
        result = mgr.semantic_index()
    console.print_json(data=result)


@memory_semantic_app.command("status")
def memory_semantic_status_cmd():
    """Show semantic memory sidecar status."""
    mgr, _ = _get_memory_manager()
    console.print_json(data=mgr.semantic_status())


@memory_semantic_app.command("reset")
def memory_semantic_reset_cmd(yes: bool = typer.Option(False, "--yes", "-y")):
    """Reset the semantic memory sidecar index."""
    mgr, _ = _get_memory_manager()
    if not yes:
        confirm = Prompt.ask("Reset semantic memory index?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=mgr.semantic_reset())


@memory_app.command("show")
def memory_show(node_id: str = typer.Argument(..., help="Node ID to display")):
    """Show a specific memory node."""
    mgr, _ = _get_memory_manager()
    node = mgr.read_node(node_id)
    if not node:
        console.print(f"[red]Node '{node_id}' not found.[/red]")
        raise typer.Exit(1)
    console.print(
        Panel(
            f"[bold]Type:[/bold] {node['type']}\n"
            f"[bold]Links:[/bold] {', '.join(node.get('links') or []) or 'none'}\n\n"
            f"{node['body']}",
            title=f"[bold cyan]{node_id}[/bold cyan]",
        )
    )


@memory_app.command("traverse")
def memory_traverse(
    node_id: str = typer.Argument(...),
    depth: int = typer.Option(2, "--depth", "-d"),
):
    """Traverse the memory graph from a node."""
    mgr, _ = _get_memory_manager()
    report = mgr.traverse_node(node_id, depth=depth)
    console.print(report or f"[dim]Node '{node_id}' not found or no connections.[/dim]")


@memory_app.command("delete")
def memory_delete(
    node_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Delete a memory node."""
    mgr, _ = _get_memory_manager()
    if not yes:
        confirm = Prompt.ask(f"Delete node '{node_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    ok = mgr.delete_node(node_id)
    if ok:
        console.print(f"[green]✓ Deleted '{node_id}'[/green]")
    else:
        console.print(f"[red]Failed to delete '{node_id}'[/red]")


@memory_app.command("export")
def memory_export(
    out: str | None = typer.Option(None, "--out", "-o"),
    fmt: str = typer.Option("json", "--format", "-f"),
):
    """Export the memory graph to JSON."""
    import json as json_mod

    mgr, username = _get_memory_manager()
    nodes = mgr.export_json()
    data = json_mod.dumps(nodes, indent=2, default=str)
    if out:
        Path(out).write_text(data)
        console.print(f"[green]✓ Exported {len(nodes)} nodes to {out}[/green]")
    else:
        console.print(data)


@memory_app.command("reset")
def memory_reset(yes: bool = typer.Option(False, "--yes", "-y")):
    """Reset (delete) all memory nodes for the current user."""
    username = _require_user()
    if not yes:
        confirm = Prompt.ask(
            f"[red]Delete ALL memory for user '{username}'? Type 'yes'[/red]",
            default="no",
        )
        if confirm.lower() != "yes":
            raise typer.Exit()

    memory_dir = user_memory_dir(username)
    if memory_dir.exists():
        # Remove all .md files but keep maggraph.toml
        for f in memory_dir.rglob("*.md"):
            f.unlink()
    console.print(f"[green]✓ Memory cleared for '{username}'[/green]")


@memory_app.command("log")
def memory_log(
    limit: int = typer.Option(20, "--limit", "-n", help="Max sessions to show"),
    user: str | None = typer.Option(None, "--user", "-u"),
):
    """Show recent session logs."""
    from magent.logging import list_session_logs
    from magent.utils import human_bytes

    logs = list_session_logs(limit=limit)
    if not logs:
        console.print("[dim]No session logs found.[/dim]")
        return

    t = Table("Session", "User", "Started", "Status", "Events", "Size")
    for entry in logs:
        if user and entry.get("user") != user:
            continue
        status = (
            "[green]complete[/green]"
            if entry.get("ended") != "active"
            else "[yellow]active[/yellow]"
        )
        t.add_row(
            entry["session"][:22],
            entry.get("user", "?"),
            entry.get("started", "?")[:19],
            status,
            str(entry.get("events", 0)),
            human_bytes(entry.get("bytes", 0)),
        )
    console.print(t)


@memory_app.command("ui")
def memory_ui(
    host: str = typer.Option("127.0.0.1", "--host", help="Loopback host to bind"),
    port: int = typer.Option(8787, "--port", "-p", help="Port for the MagGraph UI"),
):
    """Open the embedded MagGraph web dashboard for the current user's memory graph."""
    import shutil
    import subprocess

    username = _require_user()
    memory_dir = user_memory_dir(username)
    maggraph_bin = shutil.which("maggraph")
    if not maggraph_bin:
        console.print("[red]MagGraph CLI not found. Install it to use 'magent memory ui'.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]Starting MagGraph UI for '{username}' at http://{host}:{port}[/green]"
    )
    code = subprocess.run(
        [
            maggraph_bin,
            "--config",
            str(memory_dir / "maggraph.toml"),
            "ui",
            "--host",
            host,
            "--port",
            str(port),
        ]
    ).returncode
    raise typer.Exit(code)


@memory_app.command("sync")
def memory_sync(
    action: str = typer.Argument(..., help="push|pull|status"),
    message: str = typer.Option("MagAgent memory sync", "--message", "-m"),
):
    """Run MagGraph Git sync for the current user's memory graph."""
    import shutil
    import subprocess

    valid = {"push", "pull", "status"}
    if action not in valid:
        console.print(f"[red]Invalid sync action '{action}'. Choose: {', '.join(sorted(valid))}[/red]")
        raise typer.Exit(1)

    username = _require_user()
    memory_dir = user_memory_dir(username)
    maggraph_bin = shutil.which("maggraph")
    if not maggraph_bin:
        console.print("[red]MagGraph CLI not found. Install it to use 'magent memory sync'.[/red]")
        raise typer.Exit(1)

    cmd = [maggraph_bin, "--config", str(memory_dir / "maggraph.toml"), "sync", action]
    if action == "push":
        cmd += ["--message", message]
    raise typer.Exit(subprocess.run(cmd).returncode)


@memory_app.command("configure")
def memory_configure_cmd(
    mode: str = typer.Option("", "--mode", help="auto, inbox-first, or manual"),
    semantic: bool | None = typer.Option(None, "--semantic/--no-semantic"),
    write_every: int | None = typer.Option(None, "--write-every"),
    extraction_provider: str = typer.Option("", "--extraction-provider"),
    extraction_model: str = typer.Option("", "--extraction-model"),
):
    """Configure memory behavior without editing profile.toml."""
    from magent.config_ux import configure_memory

    console.print_json(
        data=configure_memory(
            _require_user(),
            mode=mode,
            semantic=semantic,
            write_every=write_every,
            extraction_provider=extraction_provider,
            extraction_model=extraction_model,
        )
    )


@memory_app.command("wizard")
def memory_wizard_cmd():
    """Interactively configure memory write and semantic recall settings."""
    from magent.config_ux import configure_memory

    mode = Prompt.ask("Memory mode", choices=["auto", "inbox-first", "manual"], default="inbox-first")
    semantic = Confirm.ask("Enable semantic memory search?", default=True)
    write_every = int(Prompt.ask("Write/check memory every N turns", default="3"))
    extraction_provider = Prompt.ask("Extraction provider (blank keeps current)", default="")
    extraction_model = Prompt.ask("Extraction model (blank keeps current)", default="")
    console.print_json(
        data=configure_memory(
            _require_user(),
            mode=mode,
            semantic=semantic,
            write_every=write_every,
            extraction_provider=extraction_provider,
            extraction_model=extraction_model,
        )
    )


# ─────────────────────────────────────────────
# Top-level commands
# ─────────────────────────────────────────────


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
    if not running:
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
def gateway_status():
    """Show whether the gateway is running and on which platforms."""
    from magent.gateway import GATEWAY_LOG_FILE, is_gateway_running

    running, pid = is_gateway_running()
    if running:
        console.print(f"[bold green]● Gateway running[/bold green] (PID {pid})")
        console.print(f"[dim]Logs: {GATEWAY_LOG_FILE}[/dim]")
    else:
        console.print("[dim]○ Gateway is not running.[/dim]")


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
    """Prompt for gateway token fields and save them."""
    from magent.config_ux import configure_gateway

    platform = platform.lower()
    bot_token = Prompt.ask(f"{platform} bot token", password=True, default="")
    app_token = ""
    if platform == "slack":
        app_token = Prompt.ask("Slack app token (xapp-...)", password=True, default="")
    result = configure_gateway(platform, bot_token=bot_token, app_token=app_token)
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
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "ghp_your_token_here" }

[mcp.servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]

[mcp.servers.postgres]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"]
timeout = 60

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
            cmd = server_info["command"]
            args_str = " ".join(server_info["args"])
            tools = server_info["tools"]

            icon = "[green]●[/green]" if ok else "[red]●[/red]"
            console.print(f"\n  {icon} [bold]{name}[/bold]  [dim]{cmd} {args_str}[/dim]")

            if ok and tools:
                table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
                table.add_column("Tool", style="white")
                table.add_column("Qualified Name", style="dim")
                table.add_column("Description")
                for tool in manager._clients[name].tools:
                    table.add_row(
                        tool.name,
                        tool.qualified_name,
                        (tool.description or "-")[:80],
                    )
                console.print(table)
            elif not ok:
                console.print(
                    "    [dim red]Failed — check config and that the command is installed[/dim red]"
                )
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
        from magent.mcp import MCPClient

        srv_cfg = mcp_servers[server]
        client = MCPClient(
            server_name=server,
            command=srv_cfg["command"],
            args=srv_cfg.get("args", []),
            env=srv_cfg.get("env"),
            timeout=srv_cfg.get("timeout", 30.0),
        )
        console.print(f"\nConnecting to [bold]{server}[/bold]...")
        ok = await client.connect()
        if not ok:
            console.print("[red]✗ Connection failed.[/red]")
            raise typer.Exit(1)

        console.print(f"[green]✓ Connected — {len(client.tools)} tools:[/green]")
        for tool in client.tools:
            console.print(f"  [bold]{tool.name}[/bold] — {tool.description}")
            console.print(f"    [dim]{tool.qualified_name}[/dim]")
        await client.disconnect()
        console.print("\n[dim]Connection closed.[/dim]")

    asyncio.run(_test())


@mcp_app.command("init")
def mcp_init() -> None:
    """Print an example MCP config block for config.toml."""
    console.print("\n[bold]Example MCP configuration:[/bold]")
    console.print(EXAMPLE_MCP_CONFIG, markup=False, highlight=False)
    console.print(f"[dim]Config: {CONFIG_DIR / 'config.toml'}[/dim]")
    console.print("[dim]Browse servers: https://github.com/modelcontextprotocol/servers[/dim]\n")
