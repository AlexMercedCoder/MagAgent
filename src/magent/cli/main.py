"""MagAgent CLI — main entry point and command groups."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from magent import __version__
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

app = typer.Typer(
    name="magent",
    help="MagAgent — CLI AI coding agent powered by MagGraph persistent memory",
    no_args_is_help=False,
    rich_markup_mode="rich",
)
user_app = typer.Typer(help="Manage user profiles", name="user")
memory_app = typer.Typer(help="Inspect and manage memory graph", name="memory")
memory_semantic_app = typer.Typer(help="Semantic memory sidecar", name="semantic")
gateway_app = typer.Typer(help="Remote gateway (Slack / Discord / Telegram)", name="gateway")
app.add_typer(user_app, name="user")
app.add_typer(memory_app, name="memory")
memory_app.add_typer(memory_semantic_app, name="semantic")
app.add_typer(gateway_app, name="gateway")
mcp_app = typer.Typer(help="Manage MCP (Model Context Protocol) servers", name="mcp")
app.add_typer(mcp_app, name="mcp")
task_app = typer.Typer(help="Persistent task ledger", name="task")
artifact_app = typer.Typer(help="Track generated artifacts", name="artifact")
project_app = typer.Typer(help="Project profiles and routines", name="project")
inbox_app = typer.Typer(help="Local command/task inbox", name="inbox")
routine_app = typer.Typer(help="Recurring routine registry", name="routine")
followup_app = typer.Typer(help="Follow-up reminders registry", name="followup")
knowledge_app = typer.Typer(help="Personal knowledge commands", name="knowledge")
api_app = typer.Typer(help="API workflow bookmarks", name="api")
patch_app = typer.Typer(help="Patch queue", name="patch")
session_app = typer.Typer(help="Session timeline and replay", name="session")
data_app = typer.Typer(help="Data workspace helpers", name="data")
policy_app = typer.Typer(help="Policy profiles", name="policy")
docs_app = typer.Typer(help="Built-in MagAgent documentation", name="docs")
checkpoint_app = typer.Typer(help="File write checkpoints", name="checkpoint")
code_app = typer.Typer(help="Code intelligence index", name="code")
test_app = typer.Typer(help="Test intelligence helpers", name="test")
workspace_app = typer.Typer(help="Workspace status and cleanup reports", name="workspace")
release_app = typer.Typer(help="Release checks and notes", name="release")
context_app = typer.Typer(help="Current project context map", name="context")
for _name, _typer in [
    ("task", task_app),
    ("artifact", artifact_app),
    ("project", project_app),
    ("inbox", inbox_app),
    ("routine", routine_app),
    ("followup", followup_app),
    ("knowledge", knowledge_app),
    ("api", api_app),
    ("patch", patch_app),
    ("session", session_app),
    ("data", data_app),
    ("policy", policy_app),
    ("docs", docs_app),
    ("checkpoint", checkpoint_app),
    ("code", code_app),
    ("test", test_app),
    ("workspace", workspace_app),
    ("release", release_app),
    ("context", context_app),
]:
    app.add_typer(_typer, name=_name)

console = Console()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _require_user() -> str:
    user = get_current_user()
    if not user:
        console.print(
            "[red]No active user. Run [bold]magent setup[/bold] or "
            "[bold]magent user create <name>[/bold] first.[/red]"
        )
        raise typer.Exit(1)
    return user


def _build_provider(config, provider_id: str | None, model: str | None):
    from magent.providers import build_provider

    p_id = provider_id or config.default_provider
    m = model or config.default_model
    api_key = config.resolve_api_key(p_id)
    p_cfg = config.provider_config(p_id)
    return build_provider(p_id, m, api_key, p_cfg)


def _build_extraction_provider(config):
    from magent.providers import build_provider

    p_id = config.extraction_provider
    m = config.extraction_model
    api_key = config.resolve_api_key(p_id)
    p_cfg = config.provider_config(p_id)
    return build_provider(p_id, m, api_key, p_cfg)


def _store():
    from magent.workbench import WorkbenchStore

    return WorkbenchStore(_require_user())


def _known_command_names() -> list[str]:
    names = []
    for command in app.registered_commands:
        if command.name:
            names.append(command.name)
    for group_info in app.registered_groups:
        if not group_info.name or not group_info.typer_instance:
            continue
        names.append(group_info.name)
        for command in group_info.typer_instance.registered_commands:
            if command.name:
                names.append(f"{group_info.name} {command.name}")
    return names


# ─────────────────────────────────────────────
# Root commands
# ─────────────────────────────────────────────


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


@app.command("ask")
def ask_cmd(
    task: str = typer.Argument(..., help="One-shot task to run non-interactively"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="Provider ID"),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name"),
    project: str | None = typer.Option(None, "--project", help="Project directory"),
):
    """Run a one-shot MagAgent task."""
    username = _require_user()
    config = load_config(username)
    cwd = project or os.getcwd()
    main_provider = _build_provider(config, provider, model)
    extract_provider = _build_extraction_provider(config)
    _run_one_shot(username, config, main_provider, extract_provider, cwd, task)


def _run_one_shot(username, config, main_provider, extract_provider, cwd, task):
    """Run a single non-interactive agent task."""
    from magent.agent import AgentSession
    from magent.tui import print_response

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
    )

    async def _run() -> str:
        try:
            return await session.chat(task)
        finally:
            await session.end_session()

    response = asyncio.run(_run())
    print_response(response)


def _run_repl(username, config, main_provider, extract_provider, cwd):
    """Run the interactive REPL with streaming output."""
    from magent.agent import AgentSession
    from magent.tui import print_banner, print_streaming_response

    print_banner(username, main_provider.display_name, cwd, config.permission_mode)

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown():
        console.print("\n[dim]Ending session...[/dim]")
        loop.run_until_complete(session.end_session())
        loop.close()

    def _signal_handler(sig, frame):
        _shutdown()
        raise SystemExit(0)


    signal.signal(signal.SIGINT, _signal_handler)

    console.print(
        "[dim]Type your message, [bold]/help[/bold] for commands, or "
        "[bold]exit[/bold] / [bold]quit[/bold] to end session.[/dim]\n"
    )

    while True:
        try:
            user_input = Prompt.ask(f"[bold cyan]({username})[/bold cyan] [bold]>[/bold]")
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue

        if user_input.strip().lower() in ("exit", "quit", "/exit", "/quit"):
            break

        if user_input.startswith("/") and _handle_slash_command(
            user_input, session, config, main_provider, loop
        ):
            continue

        # Stream the agent response
        try:
            print_streaming_response(
                session.stream_chat(user_input),
                loop,
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    console.print("\n[dim]Writing session memories...[/dim]")
    loop.run_until_complete(session.end_session())
    console.print("[dim green]Session ended. Goodbye![/dim green]")
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
                "  [cyan]/memory[/cyan]          — Show memory stats\n"
                "  [cyan]/skills[/cyan]          — List active skills\n"
                "  [cyan]/model[/cyan]           — Show current model\n"
                "  [cyan]/user[/cyan]            — Show current user\n"
                "  [cyan]/mode <mode>[/cyan]     — Set permission mode (silent/balanced/paranoid/yolo)\n"
                "  [cyan]/spawn <task>[/cyan]    — Spawn a sub-agent for a focused task\n"
                "  [cyan]/clear[/cyan]           — Clear conversation history\n"
                "  [cyan]/exit[/cyan]            — End session",
                title="[bold cyan]MagAgent Help[/bold cyan]",
            )
        )
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
            console.print(f"[green]Permission mode set to [bold]{arg}[/bold][/green]")
        else:
            console.print(f"[yellow]Current mode: {config.permission_mode}[/yellow]")
            console.print(f"[dim]Available: {', '.join(modes)}[/dim]")
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


@app.command("plan")
def plan_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    save: bool = typer.Option(False, "--save", help="Save the plan in the local workbench"),
):
    """Generate a local plan without modifying files."""
    from magent.workbench import build_plan, save_plan

    text = build_plan(project, goal)
    console.print(text)
    if save:
        item = save_plan(_store(), project, goal)
        console.print(f"[green]✓ Saved plan {item['id']}[/green]")


@app.command("plan-list")
def plan_list_cmd(status: str | None = typer.Option(None, "--status")):
    """List saved plans."""
    from magent.workbench import list_plans

    table = Table("ID", "Status", "Project", "Goal")
    for item in list_plans(_store(), status=status):
        table.add_row(item["id"], item.get("status", ""), item.get("project", ""), item.get("goal", "")[:90])
    console.print(table)


@app.command("plan-apply")
def plan_apply_cmd(
    plan_id: str = typer.Argument(...),
    run_checks: bool = typer.Option(False, "--run-checks"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Mark a saved plan applied, optionally running its suggested checks."""
    from magent.workbench import apply_plan

    if not dry_run and not yes:
        confirm = Prompt.ask(f"Apply plan '{plan_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=apply_plan(_store(), plan_id, run_checks=run_checks, dry_run=dry_run))


@app.command("plan-exec")
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


@app.command("plan-preview")
def plan_preview_cmd(plan_id: str = typer.Argument(...)):
    """Preview executable operations for a saved plan."""
    from magent.workbench import preview_plan, show_plan

    item = show_plan(_store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print(item.get("preview") or preview_plan(item))


@app.command("plan-run")
def plan_run_cmd(goal: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")):
    """Create a pending plan-run record with checks, review, and diff context."""
    from magent.workbench import save_plan_run

    item = save_plan_run(_store(), project, goal)
    console.print(f"[green]✓ Saved pending plan {item['id']}[/green]")
    console.print(item.get("plan_markdown", ""))


@app.command("plan-show")
def plan_show_cmd(plan_id: str = typer.Argument(...)):
    """Show a saved plan record."""
    from magent.workbench import show_plan

    item = show_plan(_store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@app.command("plan-discard")
def plan_discard_cmd(plan_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")):
    """Discard a saved plan."""
    from magent.workbench import discard_plan

    if not yes:
        confirm = Prompt.ask(f"Discard plan '{plan_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=discard_plan(_store(), plan_id))


@app.command("run")
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


@app.command("review")
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


@app.command("review-show")
def review_show_cmd(review_id: str = typer.Argument(...)):
    """Show a saved review."""
    from magent.workbench import review_show

    item = review_show(_store(), review_id)
    if not item:
        console.print(f"[red]Review not found: {review_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@app.command("graph")
def graph_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Show a lightweight repository import graph."""
    from magent.workbench import repo_graph

    console.print_json(data=repo_graph(project))


@app.command("test-intel")
def test_intel_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Suggest tests related to current git changes."""
    from magent.workbench import suggest_tests

    suggestions = suggest_tests(project)
    console.print("\n".join(suggestions) if suggestions else "[dim]No suggestions.[/dim]")


@code_app.command("index")
def code_index_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Build and save a code intelligence index."""
    from magent.workbench import save_code_index

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

    console.print_json(data=test_map(project))


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

    console.print_json(data=release_check(_store(), project))


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
):
    """Show memory, workbench, and project state for the current project."""
    from magent.context import context_map

    mgr, _ = _get_memory_manager()
    console.print_json(data=context_map(_store(), project=project, memory_manager=mgr, query=query))


@app.command("env-doctor")
def env_doctor_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Run project environment checks."""
    from magent.workbench import env_doctor

    table = Table("Check", "OK", "Detail")
    for check in env_doctor(project):
        table.add_row(check["check"], "yes" if check["ok"] else "no", check.get("detail", ""))
    console.print(table)


@app.command("ci")
def ci_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    logs: bool = typer.Option(False, "--logs", help="Include failed-run logs and repair hints"),
    repair_plan: bool = typer.Option(False, "--repair-plan", help="Include a local CI repair plan"),
    save: bool = typer.Option(False, "--save", help="Save repair plan to the plan ledger"),
):
    """Triage recent GitHub Actions runs with gh, when available."""
    from magent.workbench import ci_triage

    console.print_json(data=ci_triage(project, logs=logs, repair_plan=repair_plan, store=_store(), save=save))


@app.command("diagnostics")
def diagnostics_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Run available local diagnostics for the current project."""
    from magent.workbench import project_diagnostics

    console.print_json(data=project_diagnostics(project, store=_store()))


@app.command("docs-brief")
def docs_brief_cmd(project: str = typer.Option(".", "--project", "-p"), out: str | None = typer.Option(None, "--out")):
    """Generate a compact project documentation brief."""
    from magent.workbench import docs_brief

    text = docs_brief(project)
    if out:
        Path(out).write_text(text)
        console.print(f"[green]✓ Wrote {out}[/green]")
    else:
        console.print(text)


@app.command("tutorial")
def tutorial_cmd():
    """Show the built-in getting-started tutorial."""
    from magent.docs import read_topic

    console.print(read_topic("tutorial"))


@data_app.command("inspect")
def data_inspect_cmd(path: str = typer.Argument(...)):
    """Inspect a CSV or SQLite file."""
    from magent.workbench import inspect_data

    console.print_json(data=inspect_data(path))


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


@app.command("notes")
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


@app.command("stats")
def stats_cmd():
    """Show approximate local usage and token stats."""
    from magent.workbench import usage_stats

    console.print_json(data=usage_stats())


@policy_app.command("list")
def policy_list_cmd():
    """List built-in policy profiles."""
    from magent.workbench import policy_profiles

    console.print_json(data=policy_profiles())


@app.command("dashboard")
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


@app.command("ui")
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
def docs_generate_reference_cmd(out: str | None = typer.Option(None, "--out", "-o")):
    """Generate command reference Markdown from the live CLI tree."""
    from magent.docs import render_command_reference

    text = render_command_reference(_known_command_names())
    if out:
        Path(out).write_text(text, encoding="utf-8")
        console.print(f"[green]✓ Wrote {out}[/green]")
    else:
        console.print(text)


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
    console.print_json(data=mgr.semantic_index())


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


# ─────────────────────────────────────────────
# Top-level commands
# ─────────────────────────────────────────────


@app.command("setup")
def setup():
    """First-time setup wizard."""
    from magent.setup import run_setup

    run_setup()


@app.command("mode")
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


@app.command("doctor")
def doctor():
    """Run health checks: providers, maggraph, config."""
    from magent.utils import run_doctor

    run_doctor()


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
