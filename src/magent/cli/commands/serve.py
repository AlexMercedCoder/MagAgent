"""`magent serve --rpc`: the remote JSON-RPC gateway for desktop clients."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from magent.cli import shared
from magent.cli.app import app
from magent.cli.shared import console


@app.command("serve", rich_help_panel="Data & Local UI")
def serve_cmd(
    rpc: bool = typer.Option(False, "--rpc", help="Serve the JSON-RPC gateway (magent.rpc.v1)."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (loopback by default)."),
    port: int = typer.Option(7850, "--port", help="Port; 0 picks a free one."),
    root: Annotated[
        list[Path] | None,
        typer.Option(
            "--root",
            help="Project root remote callers may use (repeatable; default: current directory).",
        ),
    ] = None,
    token_stdin: bool = typer.Option(
        False, "--token-stdin", help="Read the bearer token from stdin instead of generating one."
    ),
    token_file: Annotated[
        Path | None,
        typer.Option(
            "--token-file", help="Read the bearer token from this file (keep it mode 0600)."
        ),
    ] = None,
    allow_remote: bool = typer.Option(
        False,
        "--allow-remote",
        help="Allow a non-loopback --host. The gateway speaks plain HTTP: use a TLS proxy.",
    ),
) -> None:
    """Serve MagAgent to a remote desktop client (experimental).

    Starts the `magent.rpc.v1` JSON-RPC gateway that Mag Command Center's remote
    runtime connects to: run commands, stream a run's output, answer its AAIS
    approvals, and cancel it. Every request needs `Authorization: Bearer <token>`.

    Examples:

      magent serve --rpc                        # loopback, generated token

      magent serve --rpc --root ~/code/app --port 7850

      printf '%s' "$TOKEN" | magent serve --rpc --token-stdin

    See `magent docs show rpc-gateway` for the protocol and a TLS proxy setup.
    """
    from magent.config import CONFIG_DIR
    from magent.rpc_gateway import is_loopback, serve_rpc

    if not rpc:
        console.print(
            "[red]Choose what to serve.[/red] Only --rpc is available: magent serve --rpc"
        )
        raise typer.Exit(2)
    if token_stdin and token_file:
        console.print("[red]Use either --token-stdin or --token-file, not both.[/red]")
        raise typer.Exit(2)
    token: str | None = None
    if token_stdin:
        if sys.stdin is None or sys.stdin.isatty():
            console.print("[red]--token-stdin expects the token on standard input.[/red]")
            raise typer.Exit(2)
        token = sys.stdin.read().strip()
    elif token_file is not None:
        try:
            token = token_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            console.print(f"[red]Could not read --token-file:[/red] {error}")
            raise typer.Exit(2) from error
    if token is not None and len(token) < 16:
        console.print("[red]The token must be at least 16 characters.[/red]")
        raise typer.Exit(2)
    roots = [path.expanduser() for path in (root or [Path.cwd()])]
    for path in roots:
        if not path.is_dir():
            console.print(f"[red]--root is not a directory:[/red] {path}")
            raise typer.Exit(2)
    try:
        server, gateway, info = serve_rpc(
            host=host,
            port=port,
            token=token,
            roots=roots,
            allow_remote=allow_remote,
            audit_path=CONFIG_DIR / "logs" / "rpc-gateway.jsonl",
        )
    except (ValueError, OSError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error
    if token is None:
        # Shown once so the client can connect; it is never written to disk.
        info["token"] = gateway.token
    console.print_json(data=info)
    if not is_loopback(host):
        from rich.console import Console

        Console(stderr=True).print(
            "[yellow]Serving plain HTTP on a non-loopback address. "
            "Put a TLS reverse proxy in front of it.[/yellow]"
        )
    console.print("[dim]Press Ctrl+C to stop.[/dim]")
    try:
        shared._block_until_interrupt(server)
    finally:
        gateway.shutdown()
