"""Helpers shared by the MagAgent CLI command modules.

Command modules call these through the module (``shared._store()``), so
tests can monkeypatch a helper once, here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from magent import __version__
from magent.cli.app import (
    app,
)
from magent.cli.command_context import (
    ProviderCredentialError,
    build_extraction_provider,
    build_provider,
    known_command_names,
    require_user,
    store,
)
from magent.cli.render import (
    _print_config_center,
    _print_context_map,
    _print_jobs_summary,
    _print_memory_stats,
    _print_recent_insights,
    _print_session_inbox,
    _print_session_peers,
    _print_session_receipt,
    _print_session_receipts,
    _print_session_usage,
)
from magent.config import (
    get_current_user,
)
from magent.prompt_input import read_multiline_prompt, read_user_prompt

console = Console()

MAX_PROMPT_FILE_BYTES = 8 * 1024 * 1024


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


def _resolve_ask_task(task: str | None, prompt_file: Path | None) -> str:
    """Return the task text from argv or --prompt-file, with usage errors as exit 2."""
    if task and prompt_file is not None:
        console.print("[red]Give the task as an argument or with --prompt-file, not both.[/red]")
        raise typer.Exit(2)
    if prompt_file is None:
        if not task or not task.strip():
            console.print('[red]Missing task.[/red] Try: magent ask "Summarise README.md"')
            console.print("[dim]Large prompts: magent ask --prompt-file task.md[/dim]")
            raise typer.Exit(2)
        return task
    try:
        # Read from one open handle, bounded: a stat() check followed by
        # read_text() let a device (/dev/zero), a FIFO or a file that grew in
        # between be read without limit.
        # O_NONBLOCK so opening a FIFO cannot hang before the check below.
        descriptor = os.open(prompt_file, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            mode = os.fstat(handle.fileno()).st_mode
            if stat.S_ISDIR(mode):
                raise IsADirectoryError(str(prompt_file))
            if not stat.S_ISREG(mode):
                console.print("[red]--prompt-file must be a regular file.[/red]")
                raise typer.Exit(2)
            data = handle.read(MAX_PROMPT_FILE_BYTES + 1)
        if len(data) > MAX_PROMPT_FILE_BYTES:
            console.print(
                f"[red]--prompt-file is larger than the {MAX_PROMPT_FILE_BYTES}-byte limit.[/red]"
            )
            raise typer.Exit(2)
        text = data.decode("utf-8")
    except FileNotFoundError:
        console.print(f"[red]--prompt-file not found:[/red] {escape(str(prompt_file))}")
        raise typer.Exit(2) from None
    except IsADirectoryError:
        console.print(f"[red]--prompt-file is a directory:[/red] {escape(str(prompt_file))}")
        raise typer.Exit(2) from None
    except UnicodeDecodeError:
        console.print("[red]--prompt-file must be UTF-8 text.[/red]")
        raise typer.Exit(2) from None
    except OSError as error:
        console.print(f"[red]Could not read --prompt-file:[/red] {escape(str(error))}")
        raise typer.Exit(2) from None
    if not text.strip():
        console.print("[red]--prompt-file is empty.[/red]")
        raise typer.Exit(2)
    return text


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
    approval_stdio: bool = False,
):
    """Run a single non-interactive agent task.

    In --json mode stdout is reserved for machine output: AAIS NDJSON lines
    (with --approval-stdio) and the final result document. Everything else
    the run prints (skill banners, tool narration, warnings) goes to stderr,
    so a parser never has to pick the result out of status text.
    """
    machine_out = sys.stdout
    redirect = contextlib.redirect_stdout(sys.stderr) if json_output else contextlib.nullcontext()
    with redirect:
        _run_one_shot_inner(
            username,
            config,
            main_provider,
            extract_provider,
            cwd,
            task,
            permission_mode_override=permission_mode_override,
            repair_attempts=repair_attempts,
            strict_audit=strict_audit,
            json_output=json_output,
            events_output=events_output,
            execution_task_id=execution_task_id,
            profile=profile,
            approval_stdio=approval_stdio,
            machine_out=machine_out,
        )


def _emit_machine_json(payload: dict[str, Any], out: Any) -> None:
    """Write one JSON document: pretty for a terminal, a single line otherwise."""
    is_tty = bool(getattr(out, "isatty", lambda: False)())
    text = json.dumps(payload, indent=2 if is_tty else None, default=str, ensure_ascii=False)
    out.write(text + "\n")
    out.flush()


def _run_one_shot_inner(
    username,
    config,
    main_provider,
    extract_provider,
    cwd,
    task,
    *,
    permission_mode_override: str | None,
    repair_attempts: int,
    strict_audit: bool,
    json_output: bool,
    events_output: bool,
    execution_task_id: str,
    profile,
    approval_stdio: bool,
    machine_out: Any,
):
    from magent.agent import AgentSession
    from magent.execution_bridge import SessionTaskBridge
    from magent.tui import print_response

    permission_prompt = None
    if approval_stdio:
        from magent.approval_broker import start_stdio_broker

        approval_broker, publish = start_stdio_broker(
            _store(), project=cwd, stream="magent.stdio.approvals", out=machine_out
        )

        def permission_prompt(
            description: str, tier: int, action: dict[str, Any] | None = None
        ) -> str:
            return approval_broker.request_prompt(
                description,
                tier,
                action,
                origin={"session_id": "stdio-session"},
                publish=publish,
                timeout=1800,
                allow_session=True,
                allow_persistent=str(description).lstrip().startswith("Run:"),
            )

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
        interactive_permissions=False,
        permission_prompt=permission_prompt,
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
            "memory_evidence": list(getattr(session, "memory_evidence", None) or []),
        }
        if events_output:
            payload["events"] = _one_shot_events(task, response, final_audit, session)
        _emit_machine_json(payload, machine_out)
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


def _write_research_report(
    result: dict, *, out: str | None = None, project: str | Path = "."
) -> Path:
    path = (
        Path(out).expanduser()
        if out
        else Path(project).resolve()
        / f"{_slugify_filename(str(result.get('topic') or 'research'))}.md"
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


def _print_why_last(session) -> None:
    """Explain which memories the most recent turn (or recorded run) used."""
    from magent.memory_evidence import render_lines, run_evidence_payload, task_memory_evidence

    records = list(getattr(session, "memory_evidence", None) or [])
    if records:
        payload = run_evidence_payload(
            records[-1:],
            source="session",
            session_id=str(getattr(session, "session_id", "")),
        )
        payload["title"] = "the last turn"
    else:
        payload = task_memory_evidence(get_current_user() or "", "last")
        if not payload.get("ok"):
            console.print(f"[dim]{payload.get('error')}[/dim]")
            if payload.get("hint"):
                console.print(f"[dim]{payload['hint']}[/dim]")
            return
    for index, line in enumerate(render_lines(payload)):
        console.print(escape(line) if index else f"[bold]{escape(line)}[/bold]")


def _one_shot_events(task: str, response: str, audit: dict, session) -> list[dict]:
    """Return coarse structured events for desktop timelines."""
    events: list[dict[str, Any]] = [{"type": "user_message", "content": task}]
    for record in getattr(session, "memory_evidence", None) or []:
        events.append({"type": "memory_recalled", "evidence": record})
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
                "  [cyan]/why last[/cyan]        — Show which memories the last turn used\n"
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
                task_item: dict[str, Any] | None = runtime.get(task_id)
            elif action in {"resume", "retry", "cancel"}:
                task_item = getattr(runtime, action)(
                    task_id, reason=f"{action.title()} from interactive session"
                )
            else:
                console.print("[yellow]Action must be show, resume, retry, or cancel.[/yellow]")
                return True
        except TaskRuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            return True
        if task_item is None:
            console.print(f"[red]Task not found: {task_id}[/red]")
        else:
            console.print_json(data={"ok": True, "task": task_item})
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
            console.print("[yellow]Usage: /why last | /why <memory query>[/yellow]")
            return True
        if arg.strip().lower() == "last":
            _print_why_last(session)
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


def _review_session_message(session_id: str, message_id: str, decision: str) -> None:
    from magent.session_messaging import review_held_message

    result = review_held_message(_require_user(), session_id, message_id, decision)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


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
