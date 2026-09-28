"""`magent plan <sub>`: create, review and apply saved plans.

The nine separate `plan-*` verbs are now subcommands of one `plan` group.
The old spellings still work as hidden aliases, and `magent plan "goal"`
(no subcommand) still creates a plan, so existing scripts keep running.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.prompt import Prompt
from rich.table import Table
from typer.core import TyperGroup

from magent.cli import shared
from magent.cli.app import app
from magent.cli.shared import console

PANEL = "Planning, Review & Release"


class PlanGroup(TyperGroup):
    """A group whose default subcommand is `create`.

    `magent plan "Ship the dashboard" --save` keeps working: anything that is
    not a known subcommand (or `--help`) is handed to `create`.
    """

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and args[0] not in {"--help", "-h"}:
            args = ["create", *args]
        return super().parse_args(ctx, args)


plan_app = typer.Typer(
    name="plan",
    cls=PlanGroup,
    no_args_is_help=True,
    help=(
        "Create, review and apply saved plans.\n\n"
        "Examples:\n\n"
        '  magent plan "Add JWT auth" --save\n\n'
        "  magent plan list --status pending\n\n"
        "  magent plan preview plan_0001\n\n"
        "  magent plan apply plan_0001 --run-checks\n\n"
        "The old verbs (plan-list, plan-apply, ...) remain as hidden aliases."
    ),
)


@plan_app.command("create")
def plan_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    save: bool = typer.Option(False, "--save", help="Save the plan in the local workbench"),
    executable: bool = typer.Option(
        False,
        "--executable",
        help="When saving, create an executable plan compatible with `plan preview` and `plan apply`.",
    ),
    command: Annotated[
        list[str] | None,
        typer.Option("--command", "-c", help="Shell command to include as a plan step."),
    ] = None,
    no_diff: bool = typer.Option(
        False, "--no-diff", help="Do not capture the current diff for executable plans."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable plan data."),
):
    """Generate a local plan without modifying files."""
    text, item = shared._build_and_save_plan(
        goal,
        project,
        save=save,
        executable=executable,
        commands=command or [],
        include_diff=not no_diff,
    )
    if json_output:
        console.print_json(data={"ok": True, "plan_markdown": text, "saved": item})
        return
    console.print(text)
    if item:
        mode = item.get("mode") or "draft"
        console.print(f"\n[green]✓ Saved {mode} plan {item['id']}[/green]")
        console.print("[dim]Next commands:[/dim]")
        console.print(f"  magent plan show {item['id']}")
        if executable:
            console.print(f"  magent plan preview {item['id']}")
            console.print(f"  magent plan apply {item['id']} --dry-run")
        else:
            console.print(f"  magent plan apply {item['id']} --dry-run")


@plan_app.command("list")
def plan_list_cmd(
    status: str | None = typer.Option(None, "--status", help="Only show items with this status."),
):
    """List saved plans."""
    from magent.workbench import list_plans

    table = Table("ID", "Status", "Project", "Goal")
    for item in list_plans(shared._store(), status=status):
        table.add_row(
            item["id"], item.get("status", ""), item.get("project", ""), item.get("goal", "")[:90]
        )
    console.print(table)


@plan_app.command("apply")
def plan_apply_cmd(
    plan_id: str = typer.Argument(...),
    run_checks: bool = typer.Option(
        False, "--run-checks", help="Also run the plan's suggested checks."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen without changing anything."
    ),
    sandbox: str | None = typer.Option(
        None, "--sandbox", help="Run in worktree, copy, or container sandbox"
    ),
    keep_sandbox: bool = typer.Option(
        False, "--keep-sandbox", help="Keep the sandbox afterwards for inspection."
    ),
    image: str = typer.Option(
        "python:3.12", "--image", help="Container image for --sandbox container"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Mark a saved plan applied, optionally running its suggested checks."""
    from magent.workbench import apply_plan

    if sandbox:
        from magent.sandbox import execute_plan_sandbox, sandbox_plan_preview

        if dry_run:
            console.print_json(data=sandbox_plan_preview(shared._store(), plan_id, mode=sandbox))
            return
        if not yes:
            confirm = Prompt.ask(
                f"Run plan '{plan_id}' in {sandbox} sandbox?", choices=["y", "n"], default="n"
            )
            if confirm != "y":
                raise typer.Exit()
        console.print_json(
            data=execute_plan_sandbox(
                shared._store(),
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
    console.print_json(
        data=apply_plan(shared._store(), plan_id, run_checks=run_checks, dry_run=dry_run)
    )


@plan_app.command("sandbox")
def plan_sandbox_cmd(
    plan_id: str = typer.Argument(...),
    mode: str = typer.Option(
        "worktree", "--mode", help="Sandbox kind: worktree, copy or container."
    ),
    run_checks: bool = typer.Option(
        False, "--run-checks", help="Also run the plan's suggested checks."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen without changing anything."
    ),
    keep: bool = typer.Option(False, "--keep", help="Keep the sandbox afterwards for inspection."),
    image: str = typer.Option(
        "python:3.12", "--image", help="Container image for --mode container."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Run or preview a saved plan in an isolated sandbox."""
    from magent.cli.command_context import confirm_or_exit
    from magent.sandbox import execute_plan_sandbox, sandbox_plan_preview

    if dry_run:
        console.print_json(data=sandbox_plan_preview(shared._store(), plan_id, mode=mode))
        return

    # `plan-apply --sandbox` asks before running plan operations; this ran the
    # very same operations without asking.
    confirm_or_exit(
        f"Run plan {plan_id} in a {mode} sandbox (executes its commands)?",
        assume_yes=yes,
    )
    console.print_json(
        data=execute_plan_sandbox(
            shared._store(), plan_id, mode=mode, run_checks=run_checks, keep=keep, image=image
        )
    )


@plan_app.command("exec")
def plan_exec_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    command: Annotated[
        list[str] | None,
        typer.Option("--command", "-c", help="Shell command to include as a plan step."),
    ] = None,
    no_diff: bool = typer.Option(False, "--no-diff", help="Do not include the current git diff."),
):
    """Create an executable plan from current diff and optional shell commands."""
    from magent.workbench import save_execution_plan

    item = save_execution_plan(
        shared._store(),
        project,
        goal,
        commands=command or [],
        include_diff=not no_diff,
    )
    console.print(f"[green]✓ Saved executable plan {item['id']}[/green]")
    console.print(item.get("preview", ""))


@plan_app.command("preview")
def plan_preview_cmd(plan_id: str = typer.Argument(...)):
    """Preview executable operations for a saved plan."""
    from magent.workbench import preview_plan, show_plan

    item = show_plan(shared._store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print(item.get("preview") or preview_plan(item))


@plan_app.command("run")
def plan_run_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Create a pending plan-run record with checks, review, and diff context."""
    from magent.workbench import save_plan_run

    item = save_plan_run(shared._store(), project, goal)
    console.print(f"[green]✓ Saved pending plan {item['id']}[/green]")
    console.print(item.get("plan_markdown", ""))


@plan_app.command("show")
def plan_show_cmd(plan_id: str = typer.Argument(...)):
    """Show a saved plan record."""
    from magent.workbench import show_plan

    item = show_plan(shared._store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@plan_app.command("discard")
def plan_discard_cmd(
    plan_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Discard a saved plan."""
    from magent.workbench import discard_plan

    if not yes:
        confirm = Prompt.ask(f"Discard plan '{plan_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=discard_plan(shared._store(), plan_id))


app.add_typer(plan_app, name="plan", rich_help_panel=PANEL)

# Hidden compatibility aliases for the pre-1.4 verbs.
LEGACY_ALIASES: dict[str, Any] = {
    "plan-list": plan_list_cmd,
    "plan-apply": plan_apply_cmd,
    "plan-sandbox": plan_sandbox_cmd,
    "plan-exec": plan_exec_cmd,
    "plan-preview": plan_preview_cmd,
    "plan-run": plan_run_cmd,
    "plan-show": plan_show_cmd,
    "plan-discard": plan_discard_cmd,
}
for _alias, _callback in LEGACY_ALIASES.items():
    app.command(_alias, hidden=True, rich_help_panel=PANEL)(_callback)
