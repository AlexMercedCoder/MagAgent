"""Top-level `magent` commands (everyday work, setup, help, diagnostics, planning)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from magent.cli import shared
from magent.cli.app import (
    app,
    code_app,
)
from magent.cli.command_context import (
    ProviderCredentialError,
    build_provider_for_role,
)
from magent.cli.render import (
    _print_jobs_summary,
    _print_orchestrated_preview,
    _print_orchestrated_run_result,
    _print_research_result,
)
from magent.cli.shared import console
from magent.config import (
    get_current_user,
    load_config,
)


@app.command("capabilities")
def capabilities_cmd(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    """Inspect installed runtime capabilities without running a model or opening a site."""
    from magent.capability_readiness import capability_report

    report = capability_report()
    if json_output:
        console.print_json(data=report)
    else:
        console.print(report)


@app.command("ask", rich_help_panel="Everyday Agent Work")
def ask_cmd(
    task: str | None = typer.Argument(
        None, help="One-shot task to run non-interactively (or use --prompt-file)."
    ),
    prompt_file: Annotated[
        Path | None,
        typer.Option(
            "--prompt-file",
            help="Read the task from this UTF-8 file instead of argv (for large prompts; "
            "stdin stays free for --approval-stdio).",
        ),
    ] = None,
    provider: str | None = typer.Option(None, "--provider", "-p", help="Provider ID"),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name"),
    project: str | None = typer.Option(None, "--project", help="Project directory"),
    agent: str | None = typer.Option(None, "--agent", help="Run with a named OAP agent profile"),
    permission_mode: str | None = typer.Option(
        None,
        "--permission-mode",
        help="Override permission mode for this run: silent, balanced, paranoid, or yolo.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Approve eligible tool actions non-interactively by using yolo permission mode.",
    ),
    repair_attempts: int = typer.Option(
        0,
        "--repair-attempts",
        min=0,
        max=3,
        help="Retry obvious incomplete file tasks after audit warnings.",
    ),
    strict_audit: bool = typer.Option(
        False,
        "--strict-audit",
        help="Exit nonzero when the one-shot task audit reports missing files or blocked tools.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable response, audit, and tool summary.",
    ),
    events: bool = typer.Option(
        False,
        "--events",
        help="Include structured desktop event records in JSON output.",
    ),
    execution_task_id: str = typer.Option(
        "",
        "--execution-task-id",
        hidden=True,
        help="Attach this run to a pre-created durable execution task.",
    ),
    approval_stdio: bool = typer.Option(
        False,
        "--approval-stdio",
        help="Exchange AAIS 1.0 approval envelopes as NDJSON on stdout/stdin.",
    ),
):
    """Run a one-shot MagAgent task.

    Examples:

      magent ask "Summarise README.md"

      magent ask --prompt-file task.md --project . --json

    With --json the result is one JSON document on stdout; status and progress
    text go to stderr. With --approval-stdio, AAIS envelopes are NDJSON lines on
    stdout before that final document, and decisions are read from stdin.
    """
    task = shared._resolve_ask_task(task, prompt_file)
    username = shared._require_user()
    config = load_config(username)
    permission_override = permission_mode
    if yes:
        permission_override = "yolo"
    cwd = project or os.getcwd()
    effective_profile = shared._resolve_cli_profile(agent, cwd, config)
    main_provider = shared._build_provider(
        config,
        provider or (effective_profile.provider if effective_profile else None),
        model or (effective_profile.model if effective_profile else None),
    )
    extract_provider = shared._build_extraction_provider(config)
    shared._run_one_shot(
        username,
        config,
        main_provider,
        extract_provider,
        cwd,
        task,
        permission_mode_override=permission_override,
        repair_attempts=repair_attempts,
        strict_audit=strict_audit,
        json_output=json_output,
        events_output=events,
        execution_task_id=execution_task_id,
        profile=effective_profile,
        approval_stdio=approval_stdio,
    )


@app.command("research", rich_help_panel="Everyday Agent Work")
def research_cmd(
    topic: str = typer.Argument(..., help="Research topic or question."),
    question: Annotated[
        list[str] | None,
        typer.Option("--question", "-q", help="Optional focused research question."),
    ] = None,
    max_sources: int = typer.Option(6, "--max-sources", "-n", min=1, max=20),
    fetch_sources: bool = typer.Option(
        True, "--fetch/--no-fetch", help="Fetch and excerpt source pages."
    ),
    json_output: bool = typer.Option(False, "--json/--no-json"),
    write: bool | None = typer.Option(
        None,
        "--write/--no-write",
        help="Write a Markdown research report in the active directory.",
    ),
    out: str | None = typer.Option(None, "--out", "-o", help="Output path for --write."),
    project: str = typer.Option(".", "--project", "-p", help="Active project directory."),
    agent: str | None = typer.Option(
        None, "--agent", help="Apply an OAP profile's tool and network policy."
    ),
):
    """Run deep web research without starting a full agent session."""
    from magent.tools import ToolExecutor

    config = None
    effective_profile = None
    if agent is not None:
        username = shared._require_user()
        config = load_config(username)
        effective_profile = shared._resolve_cli_profile(agent, project, config)

    async def _run() -> dict:
        tools = ToolExecutor(
            str(Path(project).resolve()),
            permission_mode=effective_profile.permission_mode if effective_profile else "silent",
            interactive_permissions=False,
            config=config,
            allowed_tools=set(effective_profile.tools) if effective_profile else None,
        )
        return await tools.deep_research(
            topic,
            questions=question or [],
            max_sources=max_sources,
            fetch_sources=fetch_sources,
        )

    result = asyncio.run(_run())
    if json_output:
        console.print_json(data=result)
    else:
        _print_research_result(result)
        should_write = write
        if should_write is None and sys.stdin.isatty() and result.get("ok"):
            should_write = Confirm.ask(
                "Write this research report to the active directory?", default=False
            )
        if should_write:
            path = shared._write_research_report(result, out=out, project=project)
            console.print(f"[green]✓ Wrote research report:[/green] {path}")
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("update", rich_help_panel="Setup & Configuration")
def update_cmd(run: bool = typer.Option(False, "--run", help="Run the detected update command.")):
    """Show or run the recommended MagAgent update command."""
    from magent.install import update_plan

    plan = update_plan()
    if not run:
        console.print_json(data=plan)
        console.print(f"[dim]Run with `magent update --run` to execute:[/dim] {plan['command']}")
        return
    from magent.command_policy import run_policy_checked_exec

    console.print(f"[dim]Running:[/dim] {plan['command']}")
    completed = run_policy_checked_exec(plan["command"], cwd=".")
    if completed.returncode:
        raise typer.Exit(completed.returncode)


@app.command("plan", rich_help_panel="Planning, Review & Release")
def plan_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    save: bool = typer.Option(False, "--save", help="Save the plan in the local workbench"),
    executable: bool = typer.Option(
        False,
        "--executable",
        help="When saving, create an executable plan compatible with plan-preview/apply.",
    ),
    command: Annotated[list[str] | None, typer.Option("--command", "-c")] = None,
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
        console.print(f"  magent plan-show {item['id']}")
        if executable:
            console.print(f"  magent plan-preview {item['id']}")
            console.print(f"  magent plan-apply {item['id']} --dry-run")
        else:
            console.print(f"  magent plan-apply {item['id']} --dry-run")


@app.command("plan-list", rich_help_panel="Planning, Review & Release")
def plan_list_cmd(status: str | None = typer.Option(None, "--status")):
    """List saved plans."""
    from magent.workbench import list_plans

    table = Table("ID", "Status", "Project", "Goal")
    for item in list_plans(shared._store(), status=status):
        table.add_row(
            item["id"], item.get("status", ""), item.get("project", ""), item.get("goal", "")[:90]
        )
    console.print(table)


@app.command("plan-apply", rich_help_panel="Planning, Review & Release")
def plan_apply_cmd(
    plan_id: str = typer.Argument(...),
    run_checks: bool = typer.Option(False, "--run-checks"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    sandbox: str | None = typer.Option(
        None, "--sandbox", help="Run in worktree, copy, or container sandbox"
    ),
    keep_sandbox: bool = typer.Option(False, "--keep-sandbox"),
    image: str = typer.Option(
        "python:3.12", "--image", help="Container image for --sandbox container"
    ),
    yes: bool = typer.Option(False, "--yes", "-y"),
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


@app.command("plan-sandbox", rich_help_panel="Planning, Review & Release")
def plan_sandbox_cmd(
    plan_id: str = typer.Argument(...),
    mode: str = typer.Option("worktree", "--mode"),
    run_checks: bool = typer.Option(False, "--run-checks"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    keep: bool = typer.Option(False, "--keep"),
    image: str = typer.Option("python:3.12", "--image"),
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


@app.command("plan-exec", rich_help_panel="Planning, Review & Release")
def plan_exec_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    command: Annotated[list[str] | None, typer.Option("--command", "-c")] = None,
    no_diff: bool = typer.Option(False, "--no-diff"),
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


@app.command("plan-preview", rich_help_panel="Planning, Review & Release")
def plan_preview_cmd(plan_id: str = typer.Argument(...)):
    """Preview executable operations for a saved plan."""
    from magent.workbench import preview_plan, show_plan

    item = show_plan(shared._store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print(item.get("preview") or preview_plan(item))


@app.command("plan-run", rich_help_panel="Planning, Review & Release")
def plan_run_cmd(
    goal: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")
):
    """Create a pending plan-run record with checks, review, and diff context."""
    from magent.workbench import save_plan_run

    item = save_plan_run(shared._store(), project, goal)
    console.print(f"[green]✓ Saved pending plan {item['id']}[/green]")
    console.print(item.get("plan_markdown", ""))


@app.command("plan-show", rich_help_panel="Planning, Review & Release")
def plan_show_cmd(plan_id: str = typer.Argument(...)):
    """Show a saved plan record."""
    from magent.workbench import show_plan

    item = show_plan(shared._store(), plan_id)
    if not item:
        console.print(f"[red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@app.command("plan-discard", rich_help_panel="Planning, Review & Release")
def plan_discard_cmd(
    plan_id: str = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y")
):
    """Discard a saved plan."""
    from magent.workbench import discard_plan

    if not yes:
        confirm = Prompt.ask(f"Discard plan '{plan_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=discard_plan(shared._store(), plan_id))


@app.command("run", rich_help_panel="Everyday Agent Work")
def run_cmd(
    goal: str = typer.Argument(...),
    budget: str = typer.Option("", "--budget", help="Human budget note, e.g. 30m"),
    project: str | None = typer.Option(None, "--project"),
):
    """Record and print an autonomous work-session plan."""
    store = shared._store()
    item = store.append("runs", {"goal": goal, "budget": budget, "status": "planned"})
    console.print(f"[green]✓ Planned run {item['id']}[/green]")
    text, _saved = shared._build_and_save_plan(goal, project or os.getcwd())
    console.print(text)


@app.command("goal", rich_help_panel="Everyday Agent Work")
def goal_cmd(
    goal: str = typer.Argument(...),
    project: str = typer.Option(".", "--project", "-p"),
    background: bool = typer.Option(
        False, "--background/--no-background", help="Queue the goal as a daemon task."
    ),
    run: bool = typer.Option(
        False, "--run/--no-run", help="Run the generated goal prompt immediately."
    ),
    verify: bool = typer.Option(
        True, "--verify/--no-verify", help="Include verifier pass instructions."
    ),
    review: bool = typer.Option(
        True, "--review/--no-review", help="Include reviewer pass instructions."
    ),
    max_loops: int = typer.Option(3, "--max-loops", min=1, max=20),
    verifier_model: str = typer.Option("cheap", "--verifier-model-role"),
    reviewer_model: str = typer.Option("review", "--reviewer-model-role"),
    orchestrated: bool = typer.Option(
        False,
        "--orchestrated/--no-orchestrated",
        help="Use staged cached-plan/sub-agent orchestration.",
    ),
    orchestrated_steps: int = typer.Option(
        3, "--orchestrated-steps", min=1, max=8, help="Maximum staged sub-agent steps."
    ),
    planning_model_role: str = typer.Option(
        "review", "--planning-model-role", help="Model role used for master/step planning metadata."
    ),
    execution_model_role: str = typer.Option(
        "coding", "--execution-model-role", help="Model role used for sub-agent execution metadata."
    ),
    provider: str | None = typer.Option(None, "--provider", help="Provider ID when using --run."),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name when using --run."),
    agent: str = typer.Option("", "--agent", help="Run this goal with a named OAP profile."),
    permission_mode: str | None = typer.Option(
        None, "--permission-mode", help="Permission mode when using --run."
    ),
    repair_attempts: int = typer.Option(
        2, "--repair-attempts", min=0, max=5, help="Audit repair attempts when using --run."
    ),
    json_output: bool = typer.Option(False, "--json"),
):
    """Create a goal loop with verifier/reviewer workflow scaffolding."""
    if orchestrated:
        from magent.goal_orchestrator import create_orchestrated_goal, run_orchestrated_goal

        if run:
            if background:
                console.print(
                    "[red]Use either --run or --background for orchestrated goals, not both.[/red]"
                )
                raise typer.Exit(2)
            username = shared._require_user()
            cfg = load_config(username)
            if provider is None and model is None:
                try:
                    main_provider = build_provider_for_role(cfg, execution_model_role)
                except ProviderCredentialError as exc:
                    console.print(f"[red]Execution model role not ready:[/red] {exc}")
                    raise typer.Exit(1) from exc
            else:
                main_provider = shared._build_provider(cfg, provider, model)
            extract_provider = shared._build_extraction_provider(cfg)

            async def _run_orchestrated():
                return await run_orchestrated_goal(
                    shared._store(),
                    goal,
                    project=project,
                    username=username,
                    provider=main_provider,
                    extraction_provider=extract_provider,
                    config=cfg,
                    verify=verify,
                    review=review,
                    max_steps=orchestrated_steps,
                    planning_model_role=planning_model_role,
                    execution_model_role=execution_model_role,
                    agent_profile=agent,
                    quiet=json_output,
                )

            result = asyncio.run(_run_orchestrated())
        else:
            result = create_orchestrated_goal(
                shared._store(),
                goal,
                project=project,
                verify=verify,
                review=review,
                max_steps=orchestrated_steps,
                planning_model_role=planning_model_role,
                execution_model_role=execution_model_role,
                agent_profile=agent,
            )
            if background:
                from magent.daemon import enqueue_task

                queued = enqueue_task(
                    shared._store(),
                    "orchestrated_goal",
                    {"id": result["plan"]["id"], "goal": goal, "agent": agent},
                    project=project,
                )
                result["queued"] = queued
                result["goal"] = (
                    shared._store().update_item("goals", result["goal"]["id"], status="queued")
                    or result["goal"]
                )
                result["plan"] = (
                    shared._store().update_item(
                        "plans",
                        result["plan"]["id"],
                        status="queued",
                        orchestration={**result["orchestration"], "status": "queued"},
                    )
                    or result["plan"]
                )
                result["orchestration"] = result["plan"]["orchestration"]
        if json_output:
            console.print_json(data=result)
            return
        goal_item = result["goal"]
        plan = result["plan"]
        orchestration = result["orchestration"]
        console.print(f"[green]✓ Created orchestrated goal {goal_item['id']}[/green]")
        console.print(Panel(plan["plan_markdown"], title="Cached Master Plan"))
        console.print(f"[dim]Saved staged plan:[/dim] {plan['id']}")
        console.print(f"[dim]Cache key:[/dim] {orchestration['cache_key']}")
        if result.get("queued"):
            console.print(f"[dim]Queued background job:[/dim] {result['queued']['id']}")
            console.print(
                "[dim]Inspect with `magent jobs` and run due work with `magent daemon run-once`.[/dim]"
            )
        else:
            console.print("[dim]Preview or run staged execution with:[/dim]")
            console.print(f"  magent goal-run {plan['id']} --dry-run")
            console.print(f"  magent goal-run {plan['id']}")
        return

    from magent.daily_driver import create_goal

    result = create_goal(
        shared._store(),
        goal,
        project=project,
        verify=verify,
        review=review,
        background=background,
        max_loops=max_loops,
        verifier_model=verifier_model,
        reviewer_model=reviewer_model,
        agent_profile=agent,
    )
    if json_output:
        console.print_json(data=result)
        return
    goal_item = result["goal"]
    plan = result["plan"]
    console.print(f"[green]✓ Created goal {goal_item['id']}[/green]")
    console.print(Panel(goal_item["prompt"], title="Goal Loop Prompt"))
    console.print(f"[dim]Saved plan:[/dim] {plan['id']}")
    if result.get("queued"):
        console.print(f"[dim]Queued background job:[/dim] {result['queued']['id']}")
        console.print(
            "[dim]Inspect with `magent jobs` and run due work with `magent daemon run-once`.[/dim]"
        )
    elif run:
        username = shared._require_user()
        cfg = load_config(username)
        main_provider = shared._build_provider(cfg, provider, model)
        extract_provider = shared._build_extraction_provider(cfg)
        effective_profile = shared._resolve_cli_profile(agent or None, project, cfg)
        if effective_profile is not None and provider is None and model is None:
            main_provider = shared._build_provider(
                cfg, effective_profile.provider, effective_profile.model
            )
        shared._run_one_shot(
            username,
            cfg,
            main_provider,
            extract_provider,
            str(Path(project).resolve()),
            goal_item["prompt"],
            permission_mode_override=permission_mode,
            repair_attempts=repair_attempts,
            strict_audit=True,
            profile=effective_profile,
        )
    else:
        console.print("[dim]Run now with:[/dim]")
        console.print(
            f"  magent goal {json.dumps(goal)} --project {json.dumps(str(Path(project).resolve()))} --run"
        )
        console.print("[dim]Or run the generated prompt directly:[/dim]")
        console.print(
            f"  magent ask {json.dumps(goal_item['prompt'])} --project {json.dumps(str(Path(project).resolve()))} --repair-attempts 2 --strict-audit"
        )


@app.command("goal-run", rich_help_panel="Everyday Agent Work")
def goal_run_cmd(
    plan_id: str = typer.Argument(..., help="Saved orchestrated plan id"),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory fallback for provider execution."
    ),
    retry_step: int = typer.Option(
        0, "--retry-step", min=0, help="Rerun a specific 1-based step and following steps."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run/--run", help="Preview the next step packet without executing."
    ),
    provider: str | None = typer.Option(None, "--provider", help="Provider ID override."),
    model: str | None = typer.Option(None, "--model", "-m", help="Model name override."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Resume, retry, or preview a saved orchestrated goal plan."""
    from magent.goal_orchestrator import preview_orchestrated_plan, run_orchestrated_plan

    store_obj = shared._store()
    try:
        preview = preview_orchestrated_plan(store_obj, plan_id, retry_step=retry_step)
    except ValueError as exc:
        preview = {"ok": False, "error": str(exc), "plan_id": plan_id}
    if not preview.get("ok"):
        if json_output:
            console.print_json(data=preview)
        else:
            console.print(f"[red]{preview.get('error')}[/red]")
        raise typer.Exit(1)
    if dry_run:
        if json_output:
            console.print_json(data=preview)
            return
        _print_orchestrated_preview(preview)
        return

    username = shared._require_user()
    cfg = load_config(username)
    execution_role = preview["orchestration"]["execution_model_role"]
    if provider is None and model is None:
        try:
            main_provider = build_provider_for_role(cfg, execution_role)
        except ProviderCredentialError as exc:
            console.print(f"[red]Execution model role not ready:[/red] {exc}")
            raise typer.Exit(1) from exc
    else:
        main_provider = shared._build_provider(cfg, provider, model)
    extract_provider = shared._build_extraction_provider(cfg)

    async def _run_saved_orchestrated():
        return await run_orchestrated_plan(
            store_obj,
            plan_id,
            username=username,
            provider=main_provider,
            extraction_provider=extract_provider,
            config=cfg,
            retry_step=retry_step,
            quiet=json_output,
        )

    result = asyncio.run(_run_saved_orchestrated())
    if json_output:
        console.print_json(data=result)
        return
    _print_orchestrated_run_result(result)
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("jobs", rich_help_panel="Everyday Agent Work")
def jobs_cmd(
    status: str = typer.Option("", "--status"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show background daemon jobs in a friendly table."""
    from magent.daily_driver import jobs_summary

    data = jobs_summary(shared._store(), status=status)
    if json_output:
        console.print_json(data=data)
        return
    _print_jobs_summary(data)


@app.command("resume", rich_help_panel="Everyday Agent Work")
def resume_cmd(
    session_id: str = typer.Argument("", help="Session id; omit for the most recent."),
    list_sessions: bool = typer.Option(False, "--list", "-l", help="List resumable sessions."),
    max_turns: int = typer.Option(40, "--max-turns", help="Most recent exchanges to restore."),
    json_output: bool = typer.Option(False, "--json"),
):
    """Resume a previous conversation.

    Conversations used to live only in memory, so closing the terminal lost the
    thread even though every turn had been logged.
    """
    from magent.session_resume import list_resumable_sessions, load_session_transcript

    if list_sessions:
        sessions = list_resumable_sessions(user=get_current_user())
        if json_output:
            console.print_json(data={"ok": True, "sessions": sessions})
            return
        if not sessions:
            console.print("[dim]No resumable sessions yet.[/dim]")
            return
        table = Table("Session", "Started", "Turns", "Opening message")
        for item in sessions:
            table.add_row(
                item["session"][:26], str(item["started"])[:19], str(item["turns"]), item["preview"]
            )
        console.print(table)
        return

    result = load_session_transcript(session_id, max_turns=max_turns)
    if json_output:
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
        return

    if not result.get("ok"):
        console.print(f"[red]{result.get('error')}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Resuming session {result['session']}[/green] ({result['turns']} turns)")
    if result.get("lossy"):
        console.print(
            "[yellow]This session predates full transcripts; turns are restored from "
            "logged previews and may be truncated.[/yellow]"
        )
    if result.get("truncated"):
        console.print(f"[dim]Only the last {max_turns} exchanges were restored.[/dim]")

    username = shared._require_user()
    config = load_config(username)
    shared._run_repl(
        username,
        config,
        shared._build_provider(config, None, None),
        shared._build_extraction_provider(config),
        os.getcwd(),
        resume=result,
    )


@app.command("statusline", rich_help_panel="Setup & Configuration")
def statusline_cmd(
    template: str = typer.Option(
        "", "--template", "-t", help="Python format template for statusline fields."
    ),
    json_output: bool = typer.Option(False, "--json"),
):
    """Render a compact shell statusline payload."""
    from magent.daily_driver import render_statusline, statusline_data

    username = get_current_user() or "default"
    config = load_config(username)
    data = statusline_data(config, username=username, cwd=os.getcwd(), store=shared._store())
    if json_output:
        console.print_json(data=data)
        return
    console.print(render_statusline(data, template=template))


@app.command("review", rich_help_panel="Planning, Review & Release")
def review_cmd(
    base: str = typer.Option("HEAD", "--since"),
    project: str = typer.Option(".", "--project", "-p"),
    json_out: bool = typer.Option(False, "--json", help="Emit structured JSON"),
    save: bool = typer.Option(False, "--save", help="Save review findings to the workbench"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="Exit non-zero if findings at or above priority exist"
    ),
):
    """Review the local git diff for common risks."""
    from magent.workbench import review_diff, review_fails_threshold, review_summary, save_review

    if save:
        item = save_review(shared._store(), project, base)
        console.print(f"[green]✓ Saved review {item['id']}[/green]")
        if json_out:
            console.print_json(data=item)
        # --save used to return before this check, so `--save --fail-on P1`
        # always exited 0 no matter what the review found.
        if fail_on and review_fails_threshold(
            (item.get("summary") or {}).get("findings", []), fail_on
        ):
            raise typer.Exit(1)
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


@app.command("review-show", rich_help_panel="Planning, Review & Release")
def review_show_cmd(review_id: str = typer.Argument(...)):
    """Show a saved review."""
    from magent.workbench import review_show

    item = review_show(shared._store(), review_id)
    if not item:
        console.print(f"[red]Review not found: {review_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@app.command("repo-graph", rich_help_panel="Code Intelligence & Testing")
def graph_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Show a lightweight repository import graph."""
    from magent.workbench import repo_graph

    console.print_json(data=repo_graph(project))


code_app.command("graph")(graph_cmd)


@app.command("test-intel", rich_help_panel="Code Intelligence & Testing")
def test_intel_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Suggest tests related to current git changes."""
    from magent.workbench import suggest_tests

    suggestions = suggest_tests(project)
    console.print("\n".join(suggestions) if suggestions else "[dim]No suggestions.[/dim]")


@app.command("env-doctor", rich_help_panel="Performance & Diagnostics")
def env_doctor_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Run project environment checks."""
    from magent.workbench import env_doctor

    table = Table("Check", "OK", "Detail")
    for check in env_doctor(project):
        table.add_row(check["check"], "yes" if check["ok"] else "no", check.get("detail", ""))
    console.print(table)


@app.command("ci", rich_help_panel="Integrations")
def ci_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    logs: bool = typer.Option(False, "--logs", help="Include failed-run logs and repair hints"),
    repair_plan: bool = typer.Option(False, "--repair-plan", help="Include a local CI repair plan"),
    save: bool = typer.Option(False, "--save", help="Save repair plan to the plan ledger"),
):
    """Triage recent GitHub Actions runs with gh, when available."""
    from magent.workbench import ci_triage

    console.print_json(
        data=ci_triage(
            project, logs=logs, repair_plan=repair_plan, store=shared._store(), save=save
        )
    )


@app.command("diagnostics", rich_help_panel="Performance & Diagnostics")
def diagnostics_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    deep: bool = typer.Option(
        False, "--deep", help="Include provider, MCP, hooks, plugins, and permissions."
    ),
    prompt: str = typer.Option(
        "", "--prompt", help="Optional prompt to verify expected artifacts from."
    ),
):
    """Run available local diagnostics for the current project."""
    if deep:
        from magent.diagnostics import deep_diagnostics

        username = shared._require_user()
        console.print_json(
            data=deep_diagnostics(
                username, load_config(username), shared._store(), project=project, prompt=prompt
            )
        )
        return
    from magent.workbench import project_diagnostics

    console.print_json(data=project_diagnostics(project, store=shared._store()))


@app.command("docs-brief", rich_help_panel="Help & Learning")
def docs_brief_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    out: str | None = typer.Option(None, "--out"),
):
    """Generate a compact project documentation brief."""
    from magent.workbench import docs_brief

    text = docs_brief(project)
    if out:
        Path(out).write_text(text)
        console.print(f"[green]✓ Wrote {out}[/green]")
    else:
        console.print(text)


@app.command("tutorial", rich_help_panel="Start Here")
def tutorial_cmd():
    """Show the built-in getting-started tutorial."""
    from magent.docs import read_topic

    console.print(read_topic("tutorial"))


@app.command("get-started", rich_help_panel="Start Here")
def get_started_cmd(
    json_output: bool = typer.Option(
        False, "--json", help="Return the guide and key commands as JSON."
    ),
):
    """Show a clear first-use guide for MagAgent."""
    from rich.markdown import Markdown

    from magent.docs import read_topic

    guide = read_topic("get-started")
    if json_output:
        console.print_json(
            data={
                "ok": True,
                "guide": guide,
                "first_commands": [
                    "magent configure",
                    "magent doctor",
                    "magent",
                    'magent ask "task"',
                    "magent profile wizard",
                    "magent docs search <query>",
                ],
            }
        )
        return
    console.print(Markdown(guide))


@app.command("notes", rich_help_panel="Workbench & Productivity")
def notes_cmd(path: str = typer.Argument(...)):
    """Ingest meeting/working notes and extract tasks/decisions."""
    from magent.workbench import ingest_notes

    text = Path(path).read_text(encoding="utf-8")
    console.print_json(data=ingest_notes(shared._store(), text))


@app.command("stats", rich_help_panel="Performance & Diagnostics")
def stats_cmd():
    """Show approximate local usage and token stats."""
    from magent.workbench import usage_stats

    console.print_json(data=usage_stats())


@app.command("dashboard", rich_help_panel="Data & Local UI")
def dashboard_cmd(
    out: str = typer.Option("magent-dashboard.html", "--out"),
    serve: bool = typer.Option(False, "--serve"),
    port: int = typer.Option(7820, "--port"),
    open_browser: bool = typer.Option(False, "--open"),
):
    """Export or serve a local workbench dashboard."""
    from magent.workbench import export_dashboard, serve_dashboard

    if serve:
        result = serve_dashboard(shared._store(), port=port, open_browser=open_browser)
        # `server` is the live ThreadingHTTPServer and is not JSON serializable;
        # print everything else and keep the handle for the blocking call below.
        console.print_json(data={key: value for key, value in result.items() if key != "server"})
        if not result.get("ok"):
            raise typer.Exit(1)
        console.print("[dim]Press Ctrl+C to stop.[/dim]")
        shared._block_until_interrupt(result.get("server"))
        return
    path = export_dashboard(shared._store(), out)
    console.print(f"[green]✓ Dashboard written to {path}[/green]")


@app.command("ui", rich_help_panel="Data & Local UI")
def ui_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    port: int = typer.Option(7830, "--port"),
    open_browser: bool = typer.Option(False, "--open"),
):
    """Serve the local operations UI."""
    from magent.ui import serve_ui

    username = shared._require_user()
    result = serve_ui(
        shared._store(), project=project, username=username, port=port, open_browser=open_browser
    )
    # The server and schedule store are live runtime handles, not response data.
    # Rendering either through Rich's JSON encoder aborts the CLI after the
    # socket has already been bound.
    console.print_json(
        data={key: value for key, value in result.items() if key not in {"server", "schedules"}}
    )
    if not result.get("ok"):
        raise typer.Exit(1)
    console.print("[dim]Press Ctrl+C to stop.[/dim]")
    shared._block_until_interrupt(result.get("server"))
    return


@app.command("setup", rich_help_panel="Start Here")
def setup():
    """First-time setup wizard."""
    from magent.setup import run_setup

    run_setup()


@app.command("configure", rich_help_panel="Start Here")
def configure_cmd():
    """Run the friendly configuration wizard."""
    from magent.setup import run_setup

    run_setup()


@app.command("onboard", rich_help_panel="Start Here")
def onboard_cmd(
    profile: str = typer.Option("coding-local", "--profile"),
    project: str = typer.Option(".", "--project", "-p"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply defaults without prompts"),
):
    """Guide a user through core MagAgent readiness."""
    from magent.ux_flows import apply_profile, init_project

    username = shared._require_user()
    selected = profile
    if not yes:
        selected = Prompt.ask("Configuration profile", default=profile)
    profile_result = apply_profile(selected, username)
    project_result = init_project(project)
    console.print_json(
        data={
            "ok": bool(profile_result.get("ok") and project_result.get("ok")),
            "profile": profile_result,
            "project": project_result,
            "next": ["magent doctor --json", "magent provider test", "magent next"],
        }
    )


@app.command("next", rich_help_panel="Start Here")
def next_cmd(project: str = typer.Option(".", "--project", "-p")):
    """Suggest useful next actions for the current repo and MagAgent setup."""
    from magent.ux_flows import next_actions

    console.print_json(
        data=next_actions(project, store=shared._store(), username=get_current_user())
    )


@app.command("mode", rich_help_panel="Setup & Configuration")
def set_mode(
    mode: str = typer.Argument(..., help="Permission mode: silent|balanced|paranoid|yolo"),
):
    """Set the default permission mode for the current user."""
    valid = ("silent", "balanced", "paranoid", "yolo")
    if mode not in valid:
        console.print(f"[red]Invalid mode '{mode}'. Choose: {', '.join(valid)}[/red]")
        raise typer.Exit(1)
    username = shared._require_user()
    from magent.config import load_user_profile, save_user_profile

    profile = load_user_profile(username)
    profile.setdefault("permissions", {})["mode"] = mode
    save_user_profile(username, profile)
    console.print(f"[green]✓ Permission mode set to [bold]{mode}[/bold][/green]")


@app.command("doctor", rich_help_panel="Start Here")
def doctor(
    fix: bool = typer.Option(False, "--fix", help="Apply safe local fixes for missing UX defaults"),
    json_output: bool = typer.Option(False, "--json", help="Emit structured doctor actions only"),
):
    """Run health checks: providers, maggraph, config."""
    from magent.config_ux import doctor_actions, fix_doctor_actions
    from magent.utils import run_doctor

    if fix:
        payload = fix_doctor_actions(get_current_user())
        console.print_json(data=payload)
        return
    payload = doctor_actions(get_current_user())
    if json_output:
        console.print_json(data=payload)
        return
    run_doctor()
    table = Table("UX Check", "OK", "Detail", "Try")
    for item in payload["actions"]:
        table.add_row(
            item["key"],
            "yes" if item["ok"] else "no",
            item["detail"],
            item.get("command", ""),
        )
    console.print(table)


@app.command("readiness", rich_help_panel="Start Here")
def readiness_cmd(
    project: str = typer.Option(".", "--project", "-p"),
    smoke: bool = typer.Option(False, "--smoke", help="Run a tiny live provider tool-use smoke."),
    provider: str | None = typer.Option(None, "--provider"),
    model: str | None = typer.Option(None, "--model"),
    timeout: int = typer.Option(90, "--timeout", help="Maximum smoke runtime in seconds."),
):
    """Show one concise setup, docs, project, provider, and model readiness report."""
    from magent.readiness import readiness_report

    username = shared._require_user()
    config = load_config(username)
    result = readiness_report(
        username,
        config,
        shared._store(),
        project=project,
        smoke=smoke,
        provider_id=provider,
        model=model,
        smoke_timeout=timeout,
    )
    console.print_json(data=result)
