"""Memory, semantic-memory and user command registrations.

Extracted from ``magent.cli.main``, which held ~85% of the command surface
inline. Behaviour is unchanged; these are the same commands in their own file.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from magent.cli.render import _print_memory_stats
from magent.config import (
    create_user,
    delete_user,
    get_current_user,
    list_users,
    set_current_user,
    user_exists,
    user_memory_dir,
)

console = Console()


def register_memory_commands(
    memory_app: typer.Typer,
    memory_semantic_app: typer.Typer,
    user_app: typer.Typer,
    *,
    store,
    require_user,
    get_memory_manager,
) -> None:
    """Register every memory/user command onto the supplied Typer apps."""
    _store = store
    _require_user = require_user

    def _get_memory_manager():
        return get_memory_manager()

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
        force: bool = typer.Option(False, "--force", help="Accept after reviewing a duplicate/conflict warning."),
        json_output: bool = typer.Option(True, "--json/--no-json", help="Emit JSON output."),
    ):
        """Review, accept, reject, or edit pending memory candidates."""
        from magent.memory_inbox import (
            accept_candidate,
            edit_candidate,
            memory_inbox,
            reject_candidate,
        )

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
            result = accept_candidate(store, mgr, candidate_id, project=project, force=force)
            console.print_json(data=result)
            if not result.get("ok"):
                raise typer.Exit(1)
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


    @memory_app.command("batch")
    def memory_batch_cmd(
        operations_json: str = typer.Option("", "--operations-json", help="JSON array of reviewed operations."),
        operations_file: str = typer.Option("", "--operations-file", help="Read operations JSON from a file."),
        preview: bool = typer.Option(False, "--preview", help="Validate without changing memory."),
        user: str | None = typer.Option(None, "--user", "-u"),
    ):
        """Preview or apply reviewed memory update/suppress/merge operations."""
        from pathlib import Path

        from magent.desktop_api import memory_apply_batch, parse_json_value

        raw = Path(operations_file).read_text(encoding="utf-8") if operations_file else operations_json
        operations = parse_json_value(raw) if raw else None
        if not isinstance(operations, list) or not all(isinstance(item, dict) for item in operations):
            console.print_json(data={"ok": False, "error": "Provide a JSON array of operation objects"})
            raise typer.Exit(1)
        result = memory_apply_batch(user or _require_user(), operations, preview=preview)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)


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

        # Filter first, then limit. Truncating to `limit` before filtering by user
        # returned an empty table whenever the newest sessions belonged to someone
        # else.
        logs = list_session_logs(limit=limit if not user else max(limit * 10, 200))
        if user:
            logs = [entry for entry in logs if entry.get("user") == user][:limit]
        if not logs:
            console.print("[dim]No session logs found.[/dim]")
            return

        t = Table("Session", "User", "Started", "Status", "Events", "Size")
        for entry in logs:
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
