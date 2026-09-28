"""Workbench command groups: tasks, artifacts, knowledge, projects, inbox, routines, follow-ups, patches, workspace, checkpoints, recipes, data, API bookmarks, policies and profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from magent.cli import shared
from magent.cli.app import (
    api_app,
    artifact_app,
    checkpoint_app,
    data_app,
    followup_app,
    inbox_app,
    knowledge_app,
    patch_app,
    policy_app,
    profile_app,
    project_app,
    recipe_app,
    routine_app,
    task_app,
    workspace_app,
)
from magent.cli.shared import console
from magent.config import (
    get_current_user,
    load_config,
)


@task_app.command("add")
def task_add_cmd(
    title: str = typer.Argument(...),
    project: str = typer.Option(
        "", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    priority: str = typer.Option("normal", "--priority", help="Priority: low, normal or high."),
):
    """Add a task to the persistent local task ledger."""
    from magent.workbench import task_add

    item = task_add(shared._store(), title, project, priority)
    console.print(f"[green]✓ Added {item['id']}[/green] {item['title']}")


@task_app.command("list")
def task_list_cmd(
    status: str | None = typer.Option(None, "--status", help="Only show items with this status."),
    project: str | None = typer.Option(
        None, "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """List tasks."""
    from magent.workbench import task_list

    tasks = task_list(shared._store(), status, project)
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

    item = shared._store().update_item("tasks", task_id, status="done", completed_at=now_iso())
    if not item:
        console.print(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ Completed {task_id}[/green]")


@task_app.command("report")
def task_report_cmd():
    """Show task counts by status and project."""
    store = shared._store()
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
    kind: str = typer.Option(
        "", "--kind", "-k", help="Artifact kind, for example report or diagram."
    ),
    title: str = typer.Option("", "--title", "-t", help="Title."),
):
    """Track a generated artifact."""
    from magent.workbench import artifact_add

    item = artifact_add(shared._store(), path, kind, title)
    console.print(f"[green]✓ Tracked {item['id']}[/green] {item['path']}")


@artifact_app.command("list")
def artifact_list_cmd():
    """List tracked artifacts."""
    table = Table("ID", "Kind", "Exists", "Title", "Path")
    for item in shared._store().read("artifacts", []):
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

    item = artifact_show(shared._store(), artifact_id)
    if not item:
        console.print(f"[red]Artifact not found: {artifact_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@artifact_app.command("checksum")
def artifact_checksum_cmd(artifact_id: str = typer.Argument(...)):
    """Calculate and store an artifact checksum."""
    from magent.workbench import artifact_checksum

    console.print_json(data=artifact_checksum(shared._store(), artifact_id))


@artifact_app.command("open")
def artifact_open_cmd(artifact_id: str = typer.Argument(...)):
    """Show the local path for an artifact."""
    from magent.workbench import artifact_open_info

    console.print_json(data=artifact_open_info(shared._store(), artifact_id))


@knowledge_app.command("remember")
def knowledge_remember_cmd(
    text: str = typer.Argument(...),
    tags: Annotated[
        list[str] | None, typer.Option("--tag", "-t", help="Tag for the note (repeatable).")
    ] = None,
):
    """Remember a personal knowledge note."""
    from magent.workbench import remember

    item = remember(shared._store(), text, tags or [])
    console.print(f"[green]✓ Remembered {item['id']}[/green]")


@knowledge_app.command("recall")
def knowledge_recall_cmd(query: str = typer.Argument(...)):
    """Recall personal knowledge notes."""
    from magent.workbench import recall

    table = Table("ID", "Tags", "Text")
    for item in recall(shared._store(), query):
        table.add_row(item["id"], ", ".join(item.get("tags", [])), item.get("text", "")[:100])
    console.print(table)


@knowledge_app.command("forget")
def knowledge_forget_cmd(item_id: str = typer.Argument(...)):
    """Forget a personal knowledge note."""
    store = shared._store()
    items = [item for item in store.read("knowledge", []) if item.get("id") != item_id]
    store.write("knowledge", items)
    console.print(f"[green]✓ Forgotten {item_id}[/green]")


@project_app.command("profile")
def project_profile_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Create or refresh a project profile."""
    from magent.workbench import save_project_profile

    profile = save_project_profile(shared._store(), path)
    console.print(Panel(str(profile), title="Project Profile"))


@project_app.command("list")
def project_list_cmd():
    """List saved project profiles."""
    table = Table("Name", "Root", "Commands")
    for item in shared._store().read("projects", []):
        table.add_row(
            item.get("name", ""), item.get("root", ""), ", ".join(item.get("commands", []))
        )
    console.print(table)


@project_app.command("commands")
def project_commands_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show discovered project test/lint/build commands."""
    from magent.workbench import infer_project_commands

    for command in infer_project_commands(Path(path).resolve()):
        console.print(command)


@project_app.command("roles")
def project_roles_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show project command roles."""
    from magent.workbench import project_command_roles

    console.print_json(data=project_command_roles(path))


@project_app.command("doctor")
def project_doctor_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Report missing/broken project command roles."""
    from magent.workbench import project_doctor

    console.print_json(data=project_doctor(path, shared._store()))


@project_app.command("playbook")
def project_playbook_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
    init: bool = typer.Option(False, "--init", help="Create a starter .magent/playbook.toml"),
):
    """Show or initialize the project playbook."""
    from magent.playbook import playbook_path, playbook_summary, playbook_template

    target = playbook_path(path)
    if init:
        if target.exists():
            console.print_json(data={"ok": False, "error": f"Playbook already exists: {target}"})
            raise typer.Exit(1)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(playbook_template(), encoding="utf-8")
    console.print_json(data=playbook_summary(path))


@project_app.command("init")
def project_init_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite existing project config and playbook files."
    ),
):
    """Create CLI-friendly MagAgent project config and playbook files."""
    from magent.ux_flows import init_project

    console.print_json(data=init_project(path, force=force))


@project_app.command("wizard")
def project_wizard_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite existing project config and playbook files."
    ),
):
    """Explain and create project config and playbook files."""
    # Call the underlying helper, not the Typer command: invoking a command as
    # a function leaves every unpassed parameter as a truthy OptionInfo.
    from magent.ux_flows import init_project

    console.print(
        Panel(
            "Creates .magent/config.toml and .magent/playbook.toml for project-specific defaults, "
            "test/build commands, review rules, and reusable routines. Existing files are preserved "
            "unless --force is supplied.",
            title="Project Bootstrap",
        )
    )
    console.print_json(data=init_project(path, force=force))


@project_app.command("config")
def project_config_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show project-local .magent/config.toml values."""
    from magent.workbench import load_project_config

    console.print_json(data=load_project_config(path))


@project_app.command("command-history")
def project_command_history_cmd(
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show learned command outcomes for a project."""
    from magent.workbench import command_history

    table = Table("Time", "OK", "Source", "Command")
    for item in command_history(shared._store(), path):
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
    path: str = typer.Option(
        ".", "--path", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Promote a command into the saved project profile."""
    from magent.workbench import promote_command

    console.print_json(data=promote_command(shared._store(), path, command))


@inbox_app.command("add")
def inbox_add_cmd(
    text: str = typer.Argument(...),
    source: str = typer.Option("cli", "--source", help="Where the item came from."),
):
    """Add an item to the local inbox."""
    item = shared._store().append("inbox", {"text": text, "source": source, "status": "new"})
    console.print(f"[green]✓ Added {item['id']}[/green]")


@inbox_app.command("list")
def inbox_list_cmd(
    status: str | None = typer.Option(None, "--status", help="Only show items with this status."),
):
    """List inbox items."""
    items = shared._store().read("inbox", [])
    if status:
        items = [item for item in items if item.get("status") == status]
    table = Table("ID", "Status", "Source", "Text")
    for item in items:
        table.add_row(
            item["id"], item.get("status", ""), item.get("source", ""), item.get("text", "")[:100]
        )
    console.print(table)


@inbox_app.command("triage")
def inbox_triage_cmd():
    """Group inbox items into tasks and notes using simple heuristics."""
    store = shared._store()
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
def routine_add_cmd(
    name: str = typer.Argument(...),
    prompt: str = typer.Argument(...),
    schedule: str = typer.Option(
        "", "--schedule", help="When to run it, for example 'daily 09:00'."
    ),
):
    """Register a recurring routine prompt."""
    item = shared._store().append(
        "routines", {"name": name, "prompt": prompt, "schedule": schedule}
    )
    console.print(f"[green]✓ Added routine {item['id']}[/green]")


@routine_app.command("list")
def routine_list_cmd():
    """List routines."""
    table = Table("ID", "Name", "Schedule", "Prompt")
    for item in shared._store().read("routines", []):
        table.add_row(
            item["id"], item.get("name", ""), item.get("schedule", ""), item.get("prompt", "")[:80]
        )
    console.print(table)


@routine_app.command("run")
def routine_run_cmd(name_or_id: str = typer.Argument(...)):
    """Print the prompt for a routine so it can be run as a one-shot task."""
    for item in shared._store().read("routines", []):
        if item.get("id") == name_or_id or item.get("name") == name_or_id:
            console.print(item.get("prompt", ""))
            return
    console.print(f"[red]Routine not found: {name_or_id}[/red]")
    raise typer.Exit(1)


@followup_app.command("add")
def followup_add_cmd(
    text: str = typer.Argument(...),
    when: str = typer.Option("", "--when", help="When to be reminded (free text or ISO time)."),
):
    """Add a follow-up reminder entry."""
    item = shared._store().append("followups", {"text": text, "when": when, "status": "open"})
    console.print(f"[green]✓ Added {item['id']}[/green]")


@followup_app.command("list")
def followup_list_cmd():
    """List follow-ups."""
    table = Table("ID", "When", "Status", "Text")
    for item in shared._store().read("followups", []):
        table.add_row(
            item["id"], item.get("when", ""), item.get("status", ""), item.get("text", "")[:100]
        )
    console.print(table)


@patch_app.command("save")
def patch_save_cmd(
    name: str = typer.Option("", "--name", help="Name for the saved patch."),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Save the current git diff to the patch queue."""
    from magent.workbench import save_patch

    item = save_patch(shared._store(), project, name)
    console.print(f"[green]✓ Saved {item['id']}[/green] {item['path']}")


@patch_app.command("list")
def patch_list_cmd():
    """List saved patches."""
    table = Table("ID", "Name", "Bytes", "Path")
    for item in shared._store().read("patches", []):
        table.add_row(
            item["id"], item.get("name", ""), str(item.get("bytes", 0)), item.get("path", "")
        )
    console.print(table)


@patch_app.command("preview")
def patch_preview_cmd(patch_id: str = typer.Argument(...)):
    """Preview a saved patch."""
    from magent.workbench import patch_preview

    console.print_json(data=patch_preview(shared._store(), patch_id))


@patch_app.command("explain")
def patch_explain_cmd(patch_id: str = typer.Argument(...)):
    """Explain saved patch impact."""
    from magent.workbench import patch_explain

    console.print_json(data=patch_explain(shared._store(), patch_id))


@patch_app.command("apply")
def patch_apply_cmd(
    patch_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Apply a saved patch after git apply --check passes."""
    from magent.workbench import apply_saved_patch

    if not yes:
        confirm = Prompt.ask(f"Apply patch '{patch_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=apply_saved_patch(shared._store(), patch_id))


@patch_app.command("revert")
def patch_revert_cmd(
    patch_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Reverse-apply a saved patch after git apply -R --check passes."""
    from magent.workbench import apply_saved_patch

    if not yes:
        confirm = Prompt.ask(f"Reverse patch '{patch_id}'?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=apply_saved_patch(shared._store(), patch_id, reverse=True))


@workspace_app.command("status")
def workspace_status_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show git/workbench status for the workspace."""
    from magent.workbench import workspace_status

    console.print_json(data=workspace_status(shared._store(), project))


@workspace_app.command("clean-report")
def workspace_clean_report_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show non-destructive cleanup suggestions."""
    from magent.workbench import workspace_clean_report

    console.print_json(data=workspace_clean_report(shared._store(), project))


@recipe_app.command("list")
def recipe_list_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
):
    """List built-in, saved, and playbook-backed workflow recipes."""
    from magent.recipes import list_recipes

    recipes = list_recipes(shared._store(), project)
    if json_output:
        # --json was accepted (hidden) but ignored, so scripts got a table.
        console.print_json(data={"ok": True, "recipes": recipes})
        return
    table = Table("Name", "Source", "Commands", "Description")
    for item in recipes:
        table.add_row(
            item.get("name", ""),
            item.get("source", "builtin"),
            str(len(item.get("commands", []))),
            item.get("description", ""),
        )
    console.print(table)


@recipe_app.command("show")
def recipe_show_cmd(
    name: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show a workflow recipe."""
    from magent.recipes import get_recipe

    recipe = get_recipe(shared._store(), name, project)
    if not recipe:
        console.print_json(data={"ok": False, "error": f"Recipe not found: {name}"})
        raise typer.Exit(1)
    console.print_json(data=recipe)


@recipe_app.command("save")
def recipe_save_cmd(
    name: str = typer.Argument(...),
    description: str = typer.Option(
        "", "--description", "-d", help="One-line description of the recipe."
    ),
    step: Annotated[
        list[str] | None, typer.Option("--step", help="Recipe step; may be repeated")
    ] = None,
    command: Annotated[
        list[str] | None,
        typer.Option("--command", "-c", help="Command; may be repeated"),
    ] = None,
):
    """Save a reusable workflow recipe."""
    from magent.recipes import save_recipe

    console.print_json(
        data=save_recipe(
            shared._store(), name, description=description, steps=step or [], commands=command or []
        )
    )


@recipe_app.command("run")
def recipe_run_cmd(
    name: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    agent: str = typer.Option(
        "", "--agent", help="Attach an OAP profile to the materialized plan."
    ),
    json_output: bool = typer.Option(False, "--json", hidden=True),
):
    """Create a pending execution plan from a workflow recipe."""
    from magent.recipes import run_recipe

    if agent:
        shared._resolve_cli_profile(agent, project, load_config(shared._require_user()))
    result = run_recipe(shared._store(), name, project, agent=agent)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@recipe_app.command("sandbox")
def recipe_sandbox_cmd(
    name: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    mode: str = typer.Option(
        "worktree", "--mode", help="Sandbox kind: worktree, copy or container."
    ),
    run_checks: bool = typer.Option(
        False, "--run-checks", help="Also run the plan's suggested checks."
    ),
    keep: bool = typer.Option(False, "--keep", help="Keep the sandbox afterwards for inspection."),
    image: str = typer.Option(
        "python:3.12", "--image", help="Container image for --mode container."
    ),
):
    """Materialize a recipe and run it in a sandbox."""
    from magent.recipes import run_recipe
    from magent.sandbox import execute_plan_sandbox

    result = run_recipe(shared._store(), name, project)
    if not result.get("ok"):
        console.print_json(data=result)
        raise typer.Exit(1)
    plan_id = result["plan"]["id"]
    console.print_json(
        data={
            "ok": True,
            "recipe": result["recipe"],
            "plan": result["plan"],
            "sandbox": execute_plan_sandbox(
                shared._store(), plan_id, mode=mode, run_checks=run_checks, keep=keep, image=image
            ),
        }
    )


@data_app.command("inspect")
def data_inspect_cmd(path: str = typer.Argument(...)):
    """Inspect a CSV or SQLite file."""
    from magent.workbench import inspect_data

    console.print_json(data=inspect_data(path))


@data_app.command("sqlite-list")
def data_sqlite_list_cmd(
    user: str | None = typer.Option(
        None, "--user", "-u", help="MagAgent user (default: the active user)."
    ),
):
    """List MagAgent SQLite databases for desktop browsing."""
    from magent.desktop_api import sqlite_list

    console.print_json(data=sqlite_list(user or shared._require_user()))


@data_app.command("sqlite-tables")
def data_sqlite_tables_cmd(
    db_name: str = typer.Option("default", "--db", help="Database name."),
    user: str | None = typer.Option(
        None, "--user", "-u", help="MagAgent user (default: the active user)."
    ),
):
    """List tables and row counts in a MagAgent SQLite database."""
    from magent.desktop_api import sqlite_tables

    console.print_json(data=sqlite_tables(user or shared._require_user(), db_name))


@data_app.command("sqlite-schema")
def data_sqlite_schema_cmd(
    table: str = typer.Argument(...),
    db_name: str = typer.Option("default", "--db", help="Database name."),
    user: str | None = typer.Option(
        None, "--user", "-u", help="MagAgent user (default: the active user)."
    ),
):
    """Show SQLite table schema for desktop browsing."""
    from magent.desktop_api import sqlite_table_schema

    result = sqlite_table_schema(user or shared._require_user(), table, db_name)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@data_app.command("sqlite-query")
def data_sqlite_query_cmd(
    sql: str = typer.Argument(...),
    db_name: str = typer.Option("default", "--db", help="Database name."),
    params: str = typer.Option("[]", "--params", help="JSON array of query params."),
    user: str | None = typer.Option(
        None, "--user", "-u", help="MagAgent user (default: the active user)."
    ),
):
    """Run a read-only SELECT/WITH query against a MagAgent SQLite database."""
    from magent.desktop_api import parse_json_value, sqlite_query

    parsed = parse_json_value(params)
    result = sqlite_query(
        user or shared._require_user(), sql, db_name, parsed if isinstance(parsed, list) else []
    )
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@api_app.command("save")
def api_save_cmd(
    name: str = typer.Argument(...),
    method: str = typer.Argument(...),
    url: str = typer.Argument(...),
):
    """Save an API endpoint bookmark."""
    item = shared._store().append(
        "api_endpoints", {"name": name, "method": method.upper(), "url": url}
    )
    console.print(f"[green]✓ Saved {item['id']}[/green]")


@api_app.command("list")
def api_list_cmd():
    """List API endpoint bookmarks."""
    table = Table("ID", "Name", "Method", "URL")
    for item in shared._store().read("api_endpoints", []):
        table.add_row(item["id"], item.get("name", ""), item.get("method", ""), item.get("url", ""))
    console.print(table)


@policy_app.command("list")
def policy_list_cmd():
    """List built-in policy profiles."""
    from magent.workbench import policy_profiles

    console.print_json(data=policy_profiles())


@checkpoint_app.command("list")
def checkpoint_list_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum number of items to return."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """List recent file checkpoints."""
    from magent.workbench import list_checkpoints

    items = list_checkpoints(shared._store(), limit=limit)
    if json_output:
        console.print_json(data={"ok": True, "checkpoints": items, "count": len(items)})
        return
    table = Table("ID", "Operation", "Status", "Path")
    for item in items:
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

    item = show_checkpoint(shared._store(), checkpoint_id)
    if not item:
        console.print(f"[red]Checkpoint not found: {checkpoint_id}[/red]")
        raise typer.Exit(1)
    console.print_json(data=item)


@checkpoint_app.command("diff")
def checkpoint_diff_cmd(
    checkpoint_id: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Show a diff from checkpoint contents to current file contents."""
    from magent.workbench import checkpoint_diff

    result = checkpoint_diff(shared._store(), checkpoint_id)
    if not result.get("ok"):
        console.print_json(data=result)
        raise typer.Exit(1)
    if json_output:
        console.print_json(data=result)
        return
    console.print(result.get("diff") or "[dim]No diff.[/dim]")


@checkpoint_app.command("restore")
def checkpoint_restore_cmd(
    checkpoint_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Restore a checkpoint."""
    from magent.workbench import restore_checkpoint

    if not yes:
        confirm = Prompt.ask(
            f"Restore checkpoint '{checkpoint_id}'?", choices=["y", "n"], default="n"
        )
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=restore_checkpoint(shared._store(), checkpoint_id))


@checkpoint_app.command("restore-last")
def checkpoint_restore_last_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Restore the most recent checkpoint."""
    from magent.workbench import restore_latest_checkpoint

    if not yes:
        confirm = Prompt.ask("Restore the latest checkpoint?", choices=["y", "n"], default="n")
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=restore_latest_checkpoint(shared._store()))


@checkpoint_app.command("session-list")
def checkpoint_session_list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """List checkpoint sessions."""
    from magent.workbench import checkpoint_sessions

    items = checkpoint_sessions(shared._store())
    if json_output:
        console.print_json(data={"ok": True, "sessions": items, "count": len(items)})
        return
    table = Table("Session", "Count", "Last", "Paths")
    for item in items:
        table.add_row(
            item.get("session_id", ""),
            str(item.get("count", 0)),
            item.get("last_at", "")[:19],
            ", ".join(item.get("paths", []))[:120],
        )
    console.print(table)


@checkpoint_app.command("session-diff")
def checkpoint_session_diff_cmd(
    session_id: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Show combined diffs for a checkpoint session."""
    from magent.workbench import checkpoint_session_diff

    result = checkpoint_session_diff(shared._store(), session_id)
    if json_output:
        console.print_json(data=result)
        return
    console.print(result.get("diff") or "[dim]No diff.[/dim]")


@checkpoint_app.command("session-restore")
def checkpoint_session_restore_cmd(
    session_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Restore all checkpoints for a session in reverse order."""
    from magent.workbench import checkpoint_session_restore

    if not yes:
        confirm = Prompt.ask(
            f"Restore checkpoint session '{session_id}'?", choices=["y", "n"], default="n"
        )
        if confirm != "y":
            raise typer.Exit()
    console.print_json(data=checkpoint_session_restore(shared._store(), session_id))


@profile_app.command("list")
def profile_list_cmd():
    """List guided configuration presets."""
    from magent.ux_flows import list_profiles

    console.print_json(data=list_profiles())


@profile_app.command("apply")
def profile_apply_cmd(name: str = typer.Argument(...)):
    """Apply a guided provider/memory/subagent preset."""
    from magent.ux_flows import apply_profile

    result = apply_profile(name, get_current_user())
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)
