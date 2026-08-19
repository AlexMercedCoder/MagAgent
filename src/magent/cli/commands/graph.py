"""Agentic Graph Specification CLI commands."""

# ruff: noqa: B008

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from magent.agraph.document import write_graph
from magent.agraph.execute import GraphExecutor, GraphRunError
from magent.agraph.generate import generate_to_file, plan_record_to_graph
from magent.agraph.plan import plan_graph
from magent.agraph.validate import validate_graph
from magent.config import get_current_user, load_config
from magent.workbench_store import WorkbenchStore


def register_graph_commands(
    graph_app: typer.Typer,
    *,
    store: Callable[[], WorkbenchStore],
    console: Console,
) -> None:
    @graph_app.command("validate")
    def validate_cmd(
        path: Path = typer.Argument(..., exists=True, dir_okay=False),
        strict: bool = typer.Option(False, "--strict"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Validate an AGS JSON or YAML document."""
        report = validate_graph(path, strict=strict)
        if json_output:
            console.print_json(data=report.as_dict())
        else:
            if not report.findings:
                console.print(f"[green]Valid[/green] {report.document.graph_id} ({report.document.digest})")
            for item in report.findings:
                style = "red" if item.severity == "error" else "yellow"
                console.print(f"[{style}]{item.code} {item.severity}[/{style}] {item.message} [dim]{item.pointer}[/dim]")
        if not report.ok:
            raise typer.Exit(1)

    @graph_app.command("plan")
    def plan_cmd(
        path: Path = typer.Argument(..., exists=True, dir_okay=False),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Preview topology, routing tiers, gates, parallelism, and cost."""
        try:
            plan = plan_graph(path)
        except ValueError as exc:
            _fail(str(exc), console)
        if json_output:
            console.print_json(data=plan.as_dict())
            return
        table = Table(title=f"Agentic Graph: {plan.graph_id}")
        table.add_column("#", justify="right")
        table.add_column("Node")
        table.add_column("Type")
        table.add_column("Tier")
        table.add_column("Parallel group")
        for index, node in enumerate(plan.nodes, 1):
            table.add_row(str(index), str(node["id"]), str(node["type"]), str(node["tier"]), str(node["level"] + 1))
        console.print(table)
        console.print(f"Projected cost: ${plan.projected_cost_usd:.2f} | Worst-case executions: {plan.worst_case_node_executions} | Max parallel: {plan.max_parallel_nodes}")
        if plan.gates:
            console.print("Gates: " + ", ".join(plan.gates))

    @graph_app.command("add")
    def add_cmd(path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
        """Add a validated graph to the user catalogue."""
        report = validate_graph(path)
        if not report.ok or not report.document:
            _fail("Graph is invalid; run `magent graph validate` for details.", console)
        catalogue = [item for item in store().read("graphs", []) if item.get("graph_id") != report.document.graph_id]
        item = {"graph_id": report.document.graph_id, "graph_digest": report.document.digest, "path": str(path.resolve()), "document": report.document.data}
        catalogue.append(item)
        store().write("graphs", catalogue)
        console.print_json(data={"ok": True, "graph": item})

    @graph_app.command("list")
    def list_cmd() -> None:
        """List saved graph documents."""
        console.print_json(data={"ok": True, "graphs": store().read("graphs", [])})

    @graph_app.command("show")
    def show_cmd(graph_id: str = typer.Argument(...)) -> None:
        """Show a saved graph document."""
        item = next((item for item in store().read("graphs", []) if item.get("graph_id") == graph_id or item.get("graph_digest") == graph_id), None)
        if not item:
            _fail(f"Graph not found: {graph_id}", console)
        console.print_json(data={"ok": True, "graph": item})

    @graph_app.command("generate")
    def generate_cmd(
        goal: str = typer.Argument(...),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        output: Path = typer.Option(Path("plan.agraph.yaml"), "--out", "-o"),
    ) -> None:
        """Generate a conservative, strictly valid graph from a goal."""
        path, report = generate_to_file(goal, output, project=project)
        if not report.ok:
            _fail("Generated graph did not pass strict validation: " + "; ".join(f"{item.code} {item.message}" for item in report.errors), console)
        console.print_json(data={"ok": True, "path": str(path), "validation": report.as_dict()})

    @graph_app.command("export-plan")
    def export_plan_cmd(
        plan_id: str = typer.Argument(...),
        output: Path = typer.Option(Path("plan.agraph.yaml"), "--out", "-o"),
    ) -> None:
        """Export an existing MagAgent plan as an AGS document."""
        plan = next((item for item in store().read("plans", []) if item.get("id") == plan_id), None)
        if not plan:
            _fail(f"Plan not found: {plan_id}", console)
        graph = plan_record_to_graph(plan)
        report = validate_graph(graph, strict=True)
        if not report.ok:
            _fail("Exported graph is invalid: " + "; ".join(f"{item.code} {item.message}" for item in report.errors), console)
        console.print_json(data={"ok": True, "path": str(write_graph(graph, output)), "validation": report.as_dict()})

    @graph_app.command("export-recipe")
    def export_recipe_cmd(
        name: str = typer.Argument(...),
        output: Path = typer.Option(Path("recipe-fragment.json"), "--out", "-o"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ) -> None:
        """Export a reusable recipe as an AGS subgraph fragment."""
        from magent.recipes import recipe_to_agraph_fragment

        result = recipe_to_agraph_fragment(store(), name, project)
        if not result.get("ok"):
            _fail(str(result.get("error")), console)
        output.write_text(json.dumps(result["fragment"], indent=2) + "\n", encoding="utf-8")
        console.print_json(data={"ok": True, "path": str(output.resolve()), "name": result["name"]})

    @graph_app.command("export-plugin")
    def export_plugin_cmd(output: Path = typer.Argument(...)) -> None:
        """Export the AGS schemas and authoring skill as a plugin pack."""
        from magent.agraph.ecosystem import export_plugin_pack

        console.print_json(data={"ok": True, **export_plugin_pack(output)})

    @graph_app.command("run")
    def run_cmd(
        path: Path = typer.Argument(..., exists=True, dir_okay=False),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        params_json: str = typer.Option("{}", "--params", help="Graph parameters as JSON."),
        dry_run: bool = typer.Option(False, "--dry-run"),
        yes: bool = typer.Option(False, "--yes", help="Approve interactive graph gates non-interactively."),
        json_output: bool = typer.Option(False, "--json"),
        agent: str = typer.Option("", "--agent", help="Run graph agent nodes under an OAP profile."),
    ) -> None:
        """Run a validated graph with durable node and run records."""
        username = get_current_user()
        if not username:
            _fail("No active user. Run `magent configure` first.", console)
        try:
            params = json.loads(params_json)
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
        except (json.JSONDecodeError, ValueError) as exc:
            _fail(f"Invalid --params: {exc}", console)

        async def approve(prompt: str, _detail: dict[str, Any]) -> bool:
            return yes or Confirm.ask(prompt, default=False)

        config = load_config(username)
        effective_profile = _effective_profile(agent, project, config) if agent else None

        async def execute() -> dict[str, Any]:
            executor = GraphExecutor(username=username, config=config, project=project, store=store(), approval=approve, assume_yes=yes, profile=effective_profile)
            return await executor.run(path, params=params, dry_run=dry_run)

        try:
            result = asyncio.run(execute())
        except GraphRunError as exc:
            _fail(str(exc), console)
        if json_output or dry_run:
            console.print_json(data=result)
        else:
            run = result["run"]
            style = "green" if result["ok"] else "red"
            console.print(f"[{style}]{run['status']}[/{style}] {run['run_id']} ({len(run['nodes'])} node records)")
            for item in run.get("diagnostics") or []:
                console.print(f"[yellow]{item['code']}[/yellow] {item['message']}")
        if not result.get("ok"):
            raise typer.Exit(1)

    @graph_app.command("status")
    def status_cmd(run_id: str = typer.Argument(...)) -> None:
        """Show one portable graph run record."""
        record = _find_run(store(), run_id)
        if not record:
            _fail(f"Graph run not found: {run_id}", console)
        console.print_json(data={"ok": True, "run": record})

    @graph_app.command("resume")
    def resume_cmd(
        run_id: str = typer.Argument(...),
        path: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        force: bool = typer.Option(False, "--force"),
        yes: bool = typer.Option(False, "--yes"),
    ) -> None:
        """Resume a graph run, guarded by the original graph digest."""
        username = get_current_user()
        record = _find_run(store(), run_id)
        if not username or not record:
            _fail("Active user or graph run not found.", console)
        source_path = str((record.get("metadata") or {}).get("source_path", ""))
        if path is None and not source_path:
            _fail("Pass --file because this run has no source path.", console)
        graph_path = path or Path(source_path)

        async def approve(prompt: str, _detail: dict[str, Any]) -> bool:
            return yes or Confirm.ask(prompt, default=False)

        async def execute() -> dict[str, Any]:
            executor = GraphExecutor(username=username, config=load_config(username), project=project, store=store(), approval=approve, assume_yes=yes)
            return await executor.run(graph_path, params=record.get("params") or {}, resume_record=record, force=force)

        result = asyncio.run(execute())
        console.print_json(data=result)


def _find_run(store: WorkbenchStore, run_id: str) -> dict[str, Any] | None:
    return next((item for item in reversed(store.read("graph_runs", [])) if item.get("run_id") == run_id), None)


def _effective_profile(name: str, project: str | Path, config: Any) -> Any:
    from magent.agent_profiles.effective import resolve_effective_profile
    from magent.agent_profiles.registry import AgentProfileRegistry
    from magent.tools.catalog import built_in_tool_definitions

    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None:
        raise GraphRunError(f"Agent profile not found: {name}", "RT012")
    granted = {
        str(item.get("function", {}).get("name", ""))
        for item in built_in_tool_definitions()
    }
    return resolve_effective_profile(resolved, config, granted)


def _fail(message: str, console: Console) -> Any:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(1)
