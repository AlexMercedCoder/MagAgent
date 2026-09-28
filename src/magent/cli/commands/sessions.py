"""Session history and local session-messaging commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from magent.cli import shared
from magent.cli.app import (
    session_app,
)
from magent.cli.render import (
    _print_session_inbox,
    _print_session_peers,
    _print_session_receipt,
    _print_session_receipts,
)
from magent.cli.shared import console
from magent.config import (
    load_config,
)


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
    limit: int = typer.Option(200, "--limit", "-n", help="Maximum number of items to return."),
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
    include_stale: bool = typer.Option(
        False, "--include-stale", help="Also list sessions that have stopped answering."
    ),
):
    """List reachable local MagAgent sessions."""
    from magent.session_messaging import list_sessions

    peers = list_sessions(shared._require_user(), include_stale=include_stale)
    if json_output:
        console.print_json(data={"ok": True, "sessions": peers, "count": len(peers)})
        return
    _print_session_peers(peers)


@session_app.command("send")
def session_send_cmd(
    target: str = typer.Argument(..., help="Durable session ID or unambiguous name."),
    message: str = typer.Argument(..., help="Plain-text coordination message."),
    task_id: str = typer.Option("", "--task", help="Ask the peer to run this as a task."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
):
    """Send a message to a live local session."""
    from magent.session_messaging import register_ephemeral_sender, send_session_message

    username = shared._require_user()
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
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
):
    """Inspect a session's accepted or held local messages."""
    from magent.session_messaging import session_inbox

    items = session_inbox(shared._require_user(), session_id, held=held)
    if json_output:
        console.print_json(data={"ok": True, "messages": items, "count": len(items)})
        return
    _print_session_inbox(items, held=held)


@session_app.command("accept")
def session_accept_cmd(
    session_id: str = typer.Argument(...), message_id: str = typer.Argument(...)
):
    """Move a held peer message into the accepted inbox."""
    shared._review_session_message(session_id, message_id, "accept")


@session_app.command("refuse")
def session_refuse_cmd(
    session_id: str = typer.Argument(...), message_id: str = typer.Argument(...)
):
    """Discard a held peer message."""
    shared._review_session_message(session_id, message_id, "refuse")


@session_app.command("policy")
def session_policy_cmd(
    policy: str = typer.Argument(..., help="accept, hold, or refuse"),
    headless_accept: bool = typer.Option(
        False,
        "--headless-accept/--no-headless-accept",
        help="Accept messages in sessions with nobody watching.",
    ),
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
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
):
    """Show delivery receipts for a session sender."""
    from magent.session_messaging import session_receipts

    items = session_receipts(shared._require_user(), sender_id)
    if json_output:
        console.print_json(data={"ok": True, "receipts": items, "count": len(items)})
        return
    _print_session_receipts(items)


@session_app.command("retry")
def session_retry_cmd(sender_id: str = typer.Argument(...)):
    """Retry unreachable messages from a live session's durable outbox."""
    from magent.session_messaging import retry_outbox

    result = retry_outbox(shared._require_user(), sender_id)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@session_app.command("doctor")
def session_doctor_cmd():
    """Check local session messaging policy, storage, roster, and queues."""
    from magent.session_messaging import messaging_diagnostics

    username = shared._require_user()
    result = messaging_diagnostics(username, load_config(username))
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)
