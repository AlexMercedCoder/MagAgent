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
gateway_app = typer.Typer(help="Remote gateway (Slack / Discord / Telegram)", name="gateway")
app.add_typer(user_app, name="user")
app.add_typer(memory_app, name="memory")
app.add_typer(gateway_app, name="gateway")
mcp_app = typer.Typer(help="Manage MCP (Model Context Protocol) servers", name="mcp")
app.add_typer(mcp_app, name="mcp")

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


# ─────────────────────────────────────────────
# Root commands
# ─────────────────────────────────────────────


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    task: Annotated[
        str | None,
        typer.Argument(help="Optional one-shot task to run non-interactively"),
    ] = None,
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
    from magent.memory import MemoryManager

    return MemoryManager(memory_dir), username


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
):
    """Search the memory graph."""
    mgr, username = _get_memory_manager()
    results = mgr.search(query, max_results=limit)
    if not results:
        console.print(f"[dim]No results for '{query}'[/dim]")
        return
    t = Table("ID", "Type", "Snippet")
    for r in results:
        t.add_row(r["id"], r.get("type", "?"), r.get("snippet", "")[:80])
    console.print(t)


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
