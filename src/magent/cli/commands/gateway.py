"""Remote chat gateway commands."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from typing import Annotated, Any

import typer
from rich.panel import Panel
from rich.prompt import Prompt

from magent.cli import shared
from magent.cli.app import (
    gateway_app,
)
from magent.cli.shared import console
from magent.config import (
    CONFIG_DIR,
    get_current_user,
    load_config,
)


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

    username = shared._require_user()
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
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
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
    bot_token: str = typer.Option(
        "", "--bot-token", help="Bot token (prefer the platform's environment variable)."
    ),
    app_token: str = typer.Option("", "--app-token", help="Slack Socket Mode app token"),
    allowed_user: Annotated[
        list[str] | None,
        typer.Option("--allowed-user", help="User id allowed to talk to the bot (repeatable)."),
    ] = None,
    allowed_channel: Annotated[
        list[str] | None,
        typer.Option("--allowed-channel", help="Channel id the bot may answer in (repeatable)."),
    ] = None,
    rate_limit: int | None = typer.Option(
        None, "--rate-limit", help="Maximum messages per minute per user."
    ),
    timeout: int | None = typer.Option(
        None, "--timeout", help="Seconds a turn may run before it is stopped."
    ),
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
        for item in Prompt.ask("Allowed user IDs (comma-separated, optional)", default="").split(
            ","
        )
        if item.strip()
    ]
    allowed_channels = [
        item.strip()
        for item in Prompt.ask("Allowed channel IDs (comma-separated, optional)", default="").split(
            ","
        )
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
