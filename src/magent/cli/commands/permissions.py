"""Permission profile UX command registrations."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

console = Console()

grants_app = typer.Typer(
    help=(
        "Review and revoke remembered approval grants.\n\n"
        "A grant is created when you answer an approval with 'Allow this exact action for "
        "this session' or 'Always allow this exact action'. New 'always' grants expire after "
        "permissions.grant_ttl_days (default 30).\n\n"
        "Examples:\n\n"
        "  magent permission grants list\n\n"
        "  magent permission grants list --active --json\n\n"
        "  magent permission grants revoke grt_0123abcd\n\n"
        "  magent permission grants revoke --expired"
    ),
    name="grants",
    no_args_is_help=True,
)


def _grant_broker():
    from pathlib import Path

    from magent.approval_broker import ApprovalBroker
    from magent.cli.command_context import require_user
    from magent.workbench_store import WorkbenchStore, WorkbenchStoreError

    try:
        return ApprovalBroker(WorkbenchStore(require_user()), project=Path.cwd())
    except WorkbenchStoreError as error:
        console.print(f"[red]{error}[/red]")
        console.print(
            "[dim]The approval state file (workbench/aais_approvals.json) is unreadable. "
            "Move it aside only after reviewing it; MagAgent never overwrites it silently.[/dim]"
        )
        raise typer.Exit(1) from error


def _read_grants(broker, *, include_inactive: bool) -> list[dict]:
    from magent.workbench_store import WorkbenchStoreError

    try:
        return broker.list_grants(include_inactive=include_inactive)
    except WorkbenchStoreError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error


@grants_app.command("list")
def grants_list_cmd(
    active: bool = typer.Option(False, "--active", help="Only show grants that still apply."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """List remembered approval grants with status, expiry and use counts.

    Grants created before expiry existed are flagged as legacy: they never
    expire until you revoke them.
    """
    from magent.approval_broker import configured_grant_ttl_days
    from magent.cli.command_context import require_user

    broker = _grant_broker()
    rows = _read_grants(broker, include_inactive=not active)
    payload = {
        "ok": True,
        "schema": "magent.approval-grants.v1",
        "grant_ttl_days": configured_grant_ttl_days(require_user()),
        "grants": rows,
    }
    if json_output:
        console.print_json(data=payload)
        return
    if not rows:
        console.print("[dim]No remembered approval grants.[/dim]")
        return
    table = Table()
    table.add_column("Grant", no_wrap=True)
    table.add_column("Scope", no_wrap=True)
    table.add_column("Status")
    table.add_column("Action", overflow="fold")
    table.add_column("Expires", no_wrap=True)
    table.add_column("Uses", justify="right")
    for row in rows:
        status = row["status"]
        if row.get("flag"):
            status += " (legacy)"
        expires = str(row.get("expires_at") or "")[:10] or (
            "never" if row["scope"] == "persistent" else "session end"
        )
        table.add_row(
            row["id"],
            row["scope"],
            status,
            row.get("action_summary") or row.get("action_name") or row["action_digest"][:19],
            expires,
            str(row.get("hits", 0)),
        )
    console.print(table)
    if any(row.get("flag") for row in rows):
        console.print(
            "[yellow]Legacy grants never expire. Revoke them with "
            "`magent permission grants revoke <id>` and approve again to get an expiring grant.[/yellow]"
        )


@grants_app.command("revoke")
def grants_revoke_cmd(
    grant_ids: Annotated[
        list[str] | None,
        typer.Argument(help="Grant ids from `magent permission grants list`."),
    ] = None,
    expired: bool = typer.Option(False, "--expired", help="Revoke every expired grant."),
    all_grants: bool = typer.Option(
        False, "--all", help="Revoke every active grant (needs --yes)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm --all."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of text."),
) -> None:
    """Revoke grants so the next matching action asks again.

    Examples: `magent permission grants revoke grt_0123abcd`,
    `magent permission grants revoke --expired`, `magent permission grants revoke --all --yes`.
    """
    from magent.cli.command_context import require_user

    ids = [item for item in (grant_ids or []) if item]
    if not ids and not expired and not all_grants:
        console.print("[red]Name at least one grant id, or pass --expired or --all.[/red]")
        console.print("[dim]See ids with `magent permission grants list`.[/dim]")
        raise typer.Exit(2)
    if all_grants and not yes:
        console.print("[red]Revoking every grant requires --yes.[/red]")
        raise typer.Exit(2)
    broker = _grant_broker()
    result = broker.revoke_grants(ids, expired=expired, all_grants=all_grants, actor=require_user())
    if json_output:
        console.print_json(data=result)
    else:
        if result["revoked"]:
            console.print(
                f"[green]Revoked {len(result['revoked'])} grant(s):[/green] "
                + ", ".join(result["revoked"])
            )
        else:
            console.print("[dim]Nothing to revoke.[/dim]")
        if result["missing"]:
            console.print("[red]Unknown grant id(s):[/red] " + ", ".join(result["missing"]))
    if not result["ok"]:
        raise typer.Exit(1)


def register_permission_commands(permission_app: typer.Typer) -> None:
    permission_app.add_typer(grants_app, name="grants")

    @permission_app.command("status")
    def permission_status_cmd() -> None:
        """Show the active user's permission profile."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_status

        console.print_json(data=permission_status(require_user()))

    @permission_app.command("explain")
    def permission_explain_cmd(mode: str = typer.Argument(...)) -> None:
        """Explain a permission mode."""
        from magent.permission_ux import permission_explain

        result = permission_explain(mode)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @permission_app.command("set")
    def permission_set_cmd(
        mode: str = typer.Argument(...),
        yes: bool = typer.Option(False, "--yes", "-y", help="Required for yolo mode."),
    ) -> None:
        """Set the active user's permission mode."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_set

        if mode.strip().lower() == "yolo" and not yes:
            console.print("[red]yolo mode requires --yes.[/red]")
            raise typer.Exit(1)
        result = permission_set(require_user(), mode)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @permission_app.command("profiles")
    def permission_profiles_cmd() -> None:
        """List named permission profiles."""
        from magent.permission_ux import permission_profiles

        console.print_json(data=permission_profiles())

    @permission_app.command("apply-profile")
    def permission_apply_profile_cmd(
        profile: str = typer.Argument(...),
        yes: bool = typer.Option(False, "--yes", "-y", help="Required for yolo profile."),
    ) -> None:
        """Apply a named permission profile."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_apply_profile

        if profile.strip().lower() == "yolo" and not yes:
            console.print("[red]yolo profile requires --yes.[/red]")
            raise typer.Exit(1)
        result = permission_apply_profile(require_user(), profile)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @permission_app.command("propose")
    def permission_propose_cmd(text: str = typer.Argument(...)) -> None:
        """Parse a natural-language permission request into a suggested action."""
        from magent.permission_ux import permission_propose

        console.print_json(data=permission_propose(text))

    @permission_app.command("classify")
    def permission_classify_cmd(
        command: str = typer.Argument(..., help="Shell command to classify (quote it)."),
        use_allowlist: bool = typer.Option(
            True,
            "--allowlist/--no-allowlist",
            help="Apply the active user's allowed_shell_patterns.",
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    ) -> None:
        """Show the risk tier a shell command would receive, and why.

        A dry run: nothing is executed. Useful when tuning
        `allowed_shell_patterns`, and it is the same entry point the classifier
        bypass regression suite exercises.
        """
        from magent.cli.command_context import require_user
        from magent.config import Config
        from magent.permissions import TIER_LABELS, describe_shell_command
        from magent.permissions.shell_parse import parse_command

        allowlist: list[str] = []
        if use_allowlist:
            try:
                allowlist = list(Config(require_user()).allowed_shell_patterns or [])
            except Exception:
                allowlist = []

        result = describe_shell_command(command, allowlist or None)
        parsed = parse_command(command)

        payload = {
            "ok": parsed.ok,
            "command": command,
            "tier": int(result.tier),
            "tier_name": result.tier.name.lower(),
            "reason": result.reason,
            "detail": result.detail,
            "allowlist_applied": bool(allowlist),
            "segments": [
                {
                    "command": segment.normalized(),
                    "head": segment.head,
                    "assignments": segment.assignments,
                    "writes": [
                        f"{redirect.operator} {redirect.target}" for redirect in segment.writes_files
                    ],
                    "substitutions": segment.substitutions,
                }
                for segment in parsed.segments
            ],
        }

        if json_output:
            console.print_json(data=payload)
            return

        console.print(f"[bold]{command}[/bold]")
        console.print(f"  tier   {TIER_LABELS[result.tier]} ({int(result.tier)})")
        console.print(f"  rule   {result.reason}" + (f" — {result.detail}" if result.detail else ""))
        if not parsed.ok:
            console.print(f"  [red]parse error: {parsed.error}[/red]")
        for index, segment in enumerate(payload["segments"], start=1):
            console.print(f"  [dim]segment {index}:[/dim] {segment['command'] or '(none)'}")
            if segment["assignments"]:
                console.print(f"    [dim]assignments:[/dim] {' '.join(segment['assignments'])}")
            for write in segment["writes"]:
                console.print(f"    [yellow]writes:[/yellow] {write}")
            for substitution in segment["substitutions"]:
                console.print(f"    [red]substitution:[/red] {substitution}")

    @permission_app.command("secrets")
    def permission_secrets_cmd(
        json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    ) -> None:
        """Check credential hygiene: plaintext keys, file modes, gateway exposure."""
        from magent.cli.command_context import require_user
        from magent.secrets_hygiene import secrets_hygiene_report

        try:
            username = require_user()
        except Exception:
            username = None

        report = secrets_hygiene_report(username)
        if json_output:
            console.print_json(data=report)
            raise typer.Exit(0 if report.get("ok") else 1)

        for finding in report.get("findings", []):
            mark = "[green]OK[/green]" if finding["ok"] else "[red]!![/red]"
            console.print(f"{mark} [bold]{finding['key']}[/bold] {finding['detail']}")
            if finding.get("command") and not finding["ok"]:
                console.print(f"   [dim]fix:[/dim] {finding['command']}")
        raise typer.Exit(0 if report.get("ok") else 1)

    @permission_app.command("trust-list")
    def permission_trust_list_cmd() -> None:
        """Show shell patterns saved by session/always approvals."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_trust_list

        console.print_json(data=permission_trust_list(require_user()))

    @permission_app.command("trust-clear")
    def permission_trust_clear_cmd(
        pattern: str = typer.Argument("", help="Exact trusted pattern to remove; omit to clear all."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Required when clearing all trusted shell patterns."),
    ) -> None:
        """Remove saved trusted shell approval patterns."""
        from magent.cli.command_context import require_user
        from magent.permission_ux import permission_trust_clear

        if not pattern and not yes:
            console.print("[red]Clearing all trusted shell patterns requires --yes.[/red]")
            raise typer.Exit(1)
        console.print_json(data=permission_trust_clear(require_user(), pattern))
