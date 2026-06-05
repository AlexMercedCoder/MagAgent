"""MagAgent CLI — main entry point and command groups."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from magent import __version__
from magent.config import (
    CONFIG_DIR,
    USERS_DIR,
    create_user,
    delete_user,
    get_current_user,
    list_users,
    load_config,
    save_global_config,
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
app.add_typer(user_app, name="user")
app.add_typer(memory_app, name="memory")

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
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Provider ID"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name"),
    project: Optional[str] = typer.Option(None, "--project", help="Project directory"),
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

    _run_repl(username, config, main_provider, extract_provider, cwd)


def _run_repl(username, config, main_provider, extract_provider, cwd):
    """Run the interactive REPL."""
    from magent.agent import AgentSession
    from magent.tui import print_banner, print_response

    print_banner(username, main_provider.display_name, cwd, config.permission_mode)

    session = AgentSession(
        username=username,
        config=config,
        provider=main_provider,
        extraction_provider=extract_provider,
        cwd=cwd,
    )

    def _signal_handler(sig, frame):
        console.print("\n[dim]Interrupted. Ending session...[/dim]")
        asyncio.get_event_loop().run_until_complete(session.end_session())
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

        # Handle slash commands
        if user_input.startswith("/"):
            if _handle_slash_command(user_input, session, config, main_provider):
                continue

        # Regular agent chat
        try:
            response = asyncio.get_event_loop().run_until_complete(
                session.chat(user_input)
            )
            print_response(response)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

    # End session
    console.print("\n[dim]Writing session memories...[/dim]")
    asyncio.get_event_loop().run_until_complete(session.end_session())
    console.print("[dim green]Session ended. Goodbye![/dim green]")


def _handle_slash_command(cmd: str, session, config, provider) -> bool:
    """Handle slash commands. Returns True if handled."""
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        console.print(Panel(
            "[bold]Available commands:[/bold]\n\n"
            "  [cyan]/help[/cyan]          — Show this help\n"
            "  [cyan]/memory[/cyan]        — Show memory stats\n"
            "  [cyan]/skills[/cyan]        — List active skills\n"
            "  [cyan]/model[/cyan]         — Show current model\n"
            "  [cyan]/user[/cyan]          — Show current user\n"
            "  [cyan]/mode <mode>[/cyan]   — Set permission mode (silent/balanced/paranoid/yolo)\n"
            "  [cyan]/clear[/cyan]         — Clear conversation history\n"
            "  [cyan]/exit[/cyan]          — End session",
            title="[bold cyan]MagAgent Help[/bold cyan]",
        ))
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

    if command == "/clear":
        session.conversation.clear()
        session.turn_count = 0
        console.print("[dim]Conversation history cleared.[/dim]")
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
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Target user (default: current)"),
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
    console.print(Panel(
        f"[bold]Type:[/bold] {node['type']}\n"
        f"[bold]Links:[/bold] {', '.join(node.get('links') or []) or 'none'}\n\n"
        f"{node['body']}",
        title=f"[bold cyan]{node_id}[/bold cyan]",
    ))


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
    out: Optional[str] = typer.Option(None, "--out", "-o"),
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
    import shutil
    memory_dir = user_memory_dir(username)
    if memory_dir.exists():
        # Remove all .md files but keep maggraph.toml
        for f in memory_dir.rglob("*.md"):
            f.unlink()
    console.print(f"[green]✓ Memory cleared for '{username}'[/green]")


# ─────────────────────────────────────────────
# Top-level commands
# ─────────────────────────────────────────────

@app.command("setup")
def setup():
    """First-time setup wizard."""
    from magent.setup import run_setup
    run_setup()


@app.command("mode")
def set_mode(mode: str = typer.Argument(..., help="Permission mode: silent|balanced|paranoid|yolo")):
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
