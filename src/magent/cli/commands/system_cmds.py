"""System, cache, release, context, skill, config, subagent, code and test command groups."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.prompt import Prompt
from rich.table import Table

from magent.cli import command_context, shared
from magent.cli.app import (
    cache_app,
    code_app,
    config_app,
    context_app,
    release_app,
    skill_app,
    subagent_app,
    system_app,
    test_app,
)
from magent.cli.render import (
    _print_context_map,
)
from magent.cli.shared import console
from magent.config import (
    CONFIG_DIR,
    get_current_user,
    load_config,
)


@system_app.command("info")
def system_info_cmd(
    json_output: bool = typer.Option(True, "--json/--no-json", help="Print machine-readable JSON."),
):
    """Return machine-readable MagAgent installation and path info."""
    from magent.desktop_api import system_info

    data = system_info()
    if json_output:
        console.print_json(data=data)
        return
    table = Table("Key", "Value")
    table.add_row("MagAgent", data["magent_version"])
    table.add_row("Python", data["python"])
    table.add_row("User", str(data["current_user"]))
    table.add_row("Config", data["paths"]["config_dir"])
    console.print(table)


@system_app.command("contracts")
def system_contracts_cmd() -> None:
    """Return versioned machine APIs and compatibility policy."""
    from magent.desktop_api import platform_contracts

    console.print_json(data=platform_contracts())


@system_app.command("compatibility")
def system_compatibility_cmd() -> None:
    """Inventory the proposed 1.0 stable, beta, and experimental surfaces."""
    from magent.contract_inventory import contract_inventory

    console.print_json(data=contract_inventory(shared._known_command_names()))


@system_app.command("migrate")
def system_migrate_cmd(
    root: str = typer.Option(
        str(CONFIG_DIR), "--root", help="MagAgent state directory to operate on."
    ),
    apply: bool = typer.Option(False, "--apply", help="Apply after creating a private backup."),
    backup_dir: str = typer.Option(
        "", "--backup-dir", help="Where to write the backup (default: next to the state)."
    ),
) -> None:
    """Preview or apply backup-first persistent-state migrations."""
    from magent.migrations import migrate_state

    result = migrate_state(root, apply=apply, backup_dir=backup_dir or None)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@system_app.command("rollback")
def system_rollback_cmd(
    backup: str = typer.Argument(...),
    root: str = typer.Option(
        str(CONFIG_DIR), "--root", help="MagAgent state directory to operate on."
    ),
    apply: bool = typer.Option(False, "--apply", help="Restore the inspected backup."),
) -> None:
    """Preview or restore a migration backup with path-containment checks."""
    from magent.migrations import rollback_state

    result = rollback_state(root, backup, apply=apply)
    console.print_json(data=result)


@system_app.command("security-report")
def system_security_report_cmd(
    output: str | None = typer.Option(None, "--output", "-o", help="Write the JSON report."),
) -> None:
    """Run credential-free security boundary probes."""
    from magent.security_assurance import (
        security_assurance_report,
        write_security_assurance_report,
    )

    report = security_assurance_report()
    if output:
        report["saved_to"] = write_security_assurance_report(report, output)
    console.print_json(data=report)
    if not report["ok"]:
        raise typer.Exit(1)


@system_app.command("ecosystem-report")
def system_ecosystem_report_cmd(
    root: str = typer.Option(".", "--root", help="Mag ecosystem workspace or MagAgent checkout."),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Write the JSON report to this path."
    ),
) -> None:
    """Generate deterministic local evidence and list external release gates."""
    from magent.ecosystem_readiness import ecosystem_readiness, write_ecosystem_report

    report = ecosystem_readiness(root)
    if output:
        report["saved_to"] = str(write_ecosystem_report(report, output))
    console.print_json(data=report)
    if not report.get("ok"):
        raise typer.Exit(1)


@cache_app.command("doctor")
def cache_doctor_cmd(
    provider: str | None = typer.Option(
        None, "--provider", "-p", help="Provider to check (default: the configured one)."
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model name (default: the configured model)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
):
    """Show prompt-cache readiness for the current provider/model."""
    from magent.agent import AGENT_STATIC_PROMPT
    from magent.cache import cache_doctor_data

    username = get_current_user()
    config = load_config(username)
    provider_id = provider or config.default_provider
    model_name = model or config.default_model
    data = cache_doctor_data(provider_id, model_name, AGENT_STATIC_PROMPT, "", config)
    if json_output:
        console.print_json(data=data)
        return
    table = Table("Field", "Value")
    table.add_row("Provider", provider_id)
    table.add_row("Model", model_name)
    table.add_row("Enabled", str(data["enabled"]))
    table.add_row("Stable prefix tokens", str(data["stable_prefix_tokens"]))
    table.add_row("Request hints", ", ".join(sorted(data["request_hints"])) or "none")
    table.add_row("Known usage fields", ", ".join(data["capabilities"]["usage_fields"]) or "none")
    console.print(table)
    recommendations = data.get("recommendations") or []
    if recommendations:
        console.print("[bold]Recommendations[/bold]")
        for item in recommendations:
            console.print(f"- {item}")
    else:
        console.print("[green]Prompt cache setup looks reasonable.[/green]")


@cache_app.command("status")
def cache_status_cmd(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
):
    """Summarize recorded prompt-cache usage from local session logs."""
    from magent.workbench import usage_stats

    stats = usage_stats()
    prompt_tokens = int(stats.get("prompt_tokens") or 0)
    cached_tokens = int(stats.get("cached_tokens") or 0)
    data = {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit_rate": round(cached_tokens / prompt_tokens, 4) if prompt_tokens else 0.0,
        "cache_write_tokens": int(stats.get("cache_write_tokens") or 0),
        "cache_miss_tokens": int(stats.get("cache_miss_tokens") or 0),
        "sessions": int(stats.get("sessions") or 0),
    }
    if json_output:
        console.print_json(data=data)
        return
    table = Table("Metric", "Value")
    for key, value in data.items():
        table.add_row(key, str(value))
    console.print(table)


@code_app.command("index")
def code_index_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Build and save a code intelligence index."""
    from magent.workbench import save_code_index

    with console.status("[bold]Indexing code...[/bold]"):
        index = save_code_index(shared._store(), project)
    console.print_json(
        data={"root": index["root"], "files": len(index["files"]), "symbols": len(index["symbols"])}
    )


@code_app.command("symbols")
def code_symbols_cmd(
    query: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Search indexed code symbols."""
    from magent.workbench import search_symbols

    table = Table("Kind", "Name", "Path", "Line")
    for item in search_symbols(shared._store(), query, project):
        table.add_row(
            item.get("kind", ""),
            item.get("name", ""),
            item.get("path", ""),
            str(item.get("line", "")),
        )
    console.print(table)


@code_app.command("related")
def code_related_cmd(
    file: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show code and tests related to a file."""
    from magent.workbench import related_code

    console.print_json(data=related_code(shared._store(), project, file))


@test_app.command("map")
def test_map_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Build a source-to-test map."""
    from magent.workbench import test_map

    with console.status("[bold]Mapping tests...[/bold]"):
        result = test_map(project)
    console.print_json(data=result)


@test_app.command("related")
def test_related_cmd(
    file: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show tests related to a source file."""
    from magent.workbench import related_tests

    for test in related_tests(project, file):
        console.print(test)


@test_app.command("explain")
def test_explain_cmd(
    file: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Explain why tests are related to a source file."""
    from magent.workbench import explain_related_tests

    console.print_json(data=explain_related_tests(project, file))


@test_app.command("run-related")
def test_run_related_cmd(
    file: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Run tests related to a source file."""
    from magent.workbench import run_related_tests

    console.print_json(data=run_related_tests(project, file))


@release_app.command("check")
def release_check_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Run release readiness checks."""
    from magent.workbench import release_check

    with console.status("[bold]Running release checks...[/bold]"):
        result = release_check(shared._store(), project)
    console.print_json(data=result)


@release_app.command("notes")
def release_notes_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    since: str = typer.Option("HEAD~5", "--since", help="Git revision to start from."),
):
    """Generate release notes from recent commits."""
    from magent.workbench import release_notes

    console.print_json(data=release_notes(project, since=since))


@release_app.command("evidence")
def release_evidence_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    eval_report: str = typer.Option("", "--eval-report", help="Eval report to include."),
    memory_report: str = typer.Option("", "--memory-report", help="Memory eval report to include."),
    performance_report: str = typer.Option(
        "", "--performance-report", help="Performance report to include."
    ),
    supply_chain_report: str = typer.Option(
        "", "--supply-chain-report", help="Supply-chain report to include."
    ),
    coverage: float | None = typer.Option(
        None, "--coverage", min=0, max=100, help="Measured test coverage, in percent."
    ),
    coverage_required: float = typer.Option(
        70, "--coverage-required", min=0, max=100, help="Minimum coverage, in percent."
    ),
    tests: str = typer.Option(
        "", "--tests", help="Recorded test result, for example '724 passed'."
    ),
    ci_url: str = typer.Option(
        "", "--ci-url", help="URL of the CI run that produced the evidence."
    ),
    artifact: Annotated[
        list[str] | None,
        typer.Option("--artifact", help="Release artifact to include (repeatable)."),
    ] = None,
    exception: Annotated[
        list[str] | None,
        typer.Option("--exception", help="Documented exception to record (repeatable)."),
    ] = None,
    out: str = typer.Option(
        "", "--out", "-o", help="Where to write the evidence bundle (default: print it)."
    ),
):
    """Create a machine-readable release qualification evidence bundle."""
    from magent.release_evidence import build_release_evidence, write_release_evidence

    report = build_release_evidence(
        project,
        eval_report=eval_report or None,
        memory_report=memory_report or None,
        performance_report=performance_report or None,
        supply_chain_report=supply_chain_report or None,
        coverage_percent=coverage,
        coverage_required=coverage_required,
        tests=tests,
        ci_url=ci_url,
        artifacts=list(artifact) if artifact else None,
        exceptions=exception,
    )
    if out:
        report["report_path"] = write_release_evidence(report, out)
    console.print_json(data=report)
    raise typer.Exit(0 if report["ok"] else 1)


@release_app.command("supply-chain")
def release_supply_chain_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    artifact: Annotated[
        list[str] | None,
        typer.Option("--artifact", help="Release artifact to include (repeatable)."),
    ] = None,
    audit_report: str = typer.Option(
        "", "--audit-report", help="Dependency audit report to include."
    ),
    out_dir: str = typer.Option(
        "dist/release-evidence", "--out-dir", help="Directory for the generated evidence."
    ),
) -> None:
    """Generate CycloneDX SBOM, provenance, hashes, and scan evidence."""
    from magent.supply_chain import build_supply_chain_evidence, write_supply_chain_bundle

    report = build_supply_chain_evidence(
        project,
        artifacts=list(artifact) if artifact else None,
        audit_report=audit_report or None,
    )
    report["files"] = write_supply_chain_bundle(report, out_dir)
    console.print_json(data=report)
    if not report["ok"]:
        raise typer.Exit(1)


@context_app.command("map")
def context_map_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    query: str = typer.Option("", "--query", "-q", help="The task to map context for."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the full machine-readable context payload."
    ),
):
    """Show memory, workbench, and project state for the current project."""
    from magent.context import context_map

    mgr, _ = command_context._get_memory_manager()
    data = context_map(shared._store(), project=project, memory_manager=mgr, query=query)
    if json_output:
        console.print_json(data=data)
        return
    _print_context_map(data)


@context_app.command("audit")
def context_audit_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
    query: str = typer.Option("", "--query", "-q", help="The task to audit context for."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
):
    """Audit active context and suggest token-saving cleanup actions."""
    from magent.context import context_map
    from magent.daily_driver import context_audit

    mgr, _ = command_context._get_memory_manager()
    data = context_audit(
        context_map(shared._store(), project=project, memory_manager=mgr, query=query)
    )
    if json_output:
        console.print_json(data=data)
        return
    _print_context_map(data["data"])
    console.print("[bold]Context Hygiene Suggestions[/bold]")
    for item in data.get("suggestions", []):
        console.print(f"- {item}")


@skill_app.command("list")
def skill_list_cmd(
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """List user and project skills available to MagAgent."""
    from magent.skills import SkillRegistry

    project_skills = Path(project).resolve() / ".magent" / "skills"
    registry = SkillRegistry(extra_dirs=[project_skills] if project_skills.exists() else None)
    registry.load(respect_lockfile=False)
    table = Table("Name", "Version", "Description", "Path")
    for item in registry.list_all():
        table.add_row(item["name"], item["version"], item["description"], item["path"])
    console.print(table)


@skill_app.command("search")
def skill_search_cmd(
    query: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Find skills relevant to a task or phrase."""
    from magent.skills import SkillRegistry

    project_skills = Path(project).resolve() / ".magent" / "skills"
    registry = SkillRegistry(extra_dirs=[project_skills] if project_skills.exists() else None)
    registry.load(respect_lockfile=False)
    table = Table("Name", "Score", "Description")
    scored = sorted(
        ((skill.score_relevance(query), skill) for skill in registry.skills),
        key=lambda item: item[0],
        reverse=True,
    )
    for score, skill in scored[:10]:
        if score <= 0:
            continue
        table.add_row(skill.name, f"{score:.2f}", skill.description[:100])
    console.print(table)


@skill_app.command("show")
def skill_show_cmd(
    name: str = typer.Argument(...),
    project: str = typer.Option(
        ".", "--project", "-p", help="Project directory (default: the current directory)."
    ),
):
    """Show one local skill's metadata and path."""
    from magent.skills import SkillRegistry

    project_skills = Path(project).resolve() / ".magent" / "skills"
    registry = SkillRegistry(extra_dirs=[project_skills] if project_skills.exists() else None)
    registry.load(respect_lockfile=False)
    for skill in registry.skills:
        if skill.name == name:
            console.print_json(
                data={
                    "ok": True,
                    "name": skill.name,
                    "version": skill.version,
                    "description": skill.description,
                    "tools_required": skill.tools_required,
                    "path": str(skill.path),
                }
            )
            return
    console.print_json(data={"ok": False, "error": f"Skill not found: {name}"})
    raise typer.Exit(1)


@config_app.command("validate")
def config_validate_cmd():
    """Validate provider, model-role, and instruction config."""
    from magent.config_validation import validate_config

    result = validate_config(get_current_user(), Path.cwd())
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@subagent_app.command("configure")
def subagent_configure_cmd(
    max_subagents: int | None = typer.Option(None, "--max", help="Maximum sub-agents per session."),
    max_parallel: int | None = typer.Option(
        None, "--parallel", help="Maximum sub-agents running at once."
    ),
    model_role: str = typer.Option("", "--model-role", help="Default model role for sub-agents."),
    sandbox_mode: str = typer.Option("", "--sandbox-mode", help="Default sandbox for sub-agents."),
):
    """Configure sub-agent caps and defaults."""
    from magent.config_ux import configure_subagents

    console.print_json(
        data=configure_subagents(
            max_subagents=max_subagents,
            max_parallel=max_parallel,
            model_role=model_role,
            sandbox_mode=sandbox_mode,
        )
    )


@subagent_app.command("status")
def subagent_status_cmd():
    """Show sub-agent configuration."""
    from magent.config_ux import ux_doctor

    console.print_json(data={"ok": True, "subagents": ux_doctor(get_current_user())["subagents"]})


@subagent_app.command("run")
def subagent_run_cmd(
    task: str = typer.Argument(...),
    provider: str | None = typer.Option(
        None, "--provider", "-p", help="Provider id (default: the configured provider)."
    ),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model name (default: the configured model)."
    ),
    project: str | None = typer.Option(
        None, "--project", help="Project directory (default: the current directory)."
    ),
):
    """Run one focused sub-agent task from the CLI."""
    username = shared._require_user()
    config = load_config(username)
    cwd = project or os.getcwd()
    main_provider = shared._build_provider(config, provider, model)
    extract_provider = shared._build_extraction_provider(config)

    async def _run():
        from magent.subagents import SubAgentRunner

        runner = SubAgentRunner(username, main_provider, extract_provider, cwd, config)
        result = await runner.spawn("cli_subagent", task)
        return result

    result = asyncio.run(_run())
    console.print_json(data=result.__dict__)


@subagent_app.command("wizard")
def subagent_wizard_cmd():
    """Explain and configure subagent caps, models, and isolation."""
    from magent.cli.wizard_guidance import explain_options
    from magent.config_ux import configure_subagents

    explain_options(
        console,
        "Subagent settings",
        [
            (
                "maximum",
                "Total focused workers the main agent may create for one task; 0 disables delegation.",
            ),
            (
                "parallel",
                "Workers allowed to run concurrently. Lower values reduce resource and quota spikes.",
            ),
            ("model role", "Configured model role used by workers, usually coding or cheap."),
            ("blank", "Run in the current project with normal checkpoint protections."),
            ("copy", "Use an isolated filesystem copy."),
            ("worktree", "Use an isolated Git worktree when the project is a repository."),
            ("container", "Use the configured container runtime for strongest isolation."),
        ],
        note="Profile-specific subagent limits can narrow these global caps but cannot raise them.",
    )
    max_subagents = int(Prompt.ask("Maximum sub-agents", default="3"))
    max_parallel = int(Prompt.ask("Maximum parallel sub-agents", default="2"))
    model_role = Prompt.ask("Model role", default="coding")
    sandbox_mode = Prompt.ask("Sandbox mode (blank, copy, worktree, container)", default="")
    console.print_json(
        data=configure_subagents(
            max_subagents=max_subagents,
            max_parallel=max_parallel,
            model_role=model_role,
            sandbox_mode=sandbox_mode,
        )
    )
