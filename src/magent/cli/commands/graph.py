"""Agentic Graph Specification CLI commands."""

# ruff: noqa: B008

from __future__ import annotations

import asyncio
import json
import sys
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
from magent.agraph.plan import plan_graph, resolved_plan
from magent.agraph.validate import validate_graph
from magent.config import get_current_user, load_config
from magent.workbench_store import WorkbenchStore


def register_graph_commands(
    graph_app: typer.Typer,
    *,
    store: Callable[[], WorkbenchStore],
    console: Console,
) -> None:
    def input_document(path: str) -> dict[str, Any]:
        text = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("Graph input must be a JSON object")
        return value

    def registry_config(project: str | Path) -> Any | None:
        username = get_current_user()
        return load_config(username) if username else None

    @graph_app.command("schema")
    def schema_cmd(project: Path = typer.Option(Path("."), "--project", "-p")) -> None:
        """Return the versioned graph editor contract and local profiles."""
        from magent.agraph.authoring import authoring_contract

        console.print_json(data=authoring_contract(project, registry_config(project)))

    @graph_app.command("inspect")
    def inspect_cmd(path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
        """Load a normalized graph document for a visual editor."""
        from magent.agraph.authoring import inspect_graph

        result = inspect_graph(path)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @graph_app.command("preview")
    def preview_cmd(
        input_path: str = typer.Option("-", "--input"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ) -> None:
        """Validate and plan an unsaved graph supplied as JSON."""
        from magent.agraph.authoring import preview_graph

        try:
            result = preview_graph(input_document(input_path), project=project, config=registry_config(project))
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @graph_app.command("apply")
    def apply_cmd(
        path: Path = typer.Argument(...),
        input_path: str = typer.Option("-", "--input"),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        expected_digest: str = typer.Option("", "--expected-digest"),
    ) -> None:
        """Conflict-safely save a validated graph supplied as JSON."""
        from magent.agraph.authoring import save_graph

        try:
            result = save_graph(input_document(input_path), path, project=project, config=registry_config(project), expected_digest=expected_digest)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @graph_app.command("generate-draft")
    def generate_draft_cmd(
        goal: str = typer.Argument(...),
        project: Path = typer.Option(Path("."), "--project", "-p"),
    ) -> None:
        """Return a generated graph draft without writing or running it."""
        from magent.agraph.authoring import generate_draft

        console.print_json(data=generate_draft(goal, project=project))

    @graph_app.command("rename-node")
    def rename_node_cmd(
        old_id: str = typer.Argument(...),
        new_id: str = typer.Argument(...),
        input_path: str = typer.Option("-", "--input"),
    ) -> None:
        """Safely rename a node in an unsaved graph document."""
        from magent.agraph.authoring import rename_node

        result = rename_node(input_document(input_path), old_id, new_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @graph_app.command("duplicate-node")
    def duplicate_node_cmd(
        node_id: str = typer.Argument(...),
        new_id: str = typer.Argument(...),
        input_path: str = typer.Option("-", "--input"),
    ) -> None:
        """Duplicate a node while preserving its type-specific contract."""
        from magent.agraph.authoring import duplicate_node

        result = duplicate_node(input_document(input_path), node_id, new_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @graph_app.command("model-draft")
    def model_draft_cmd(
        goal: str = typer.Argument(...),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        input_path: str = typer.Option("", "--input"),
        instruction: str = typer.Option("", "--instruction"),
    ) -> None:
        """Generate or improve a graph through the configured planning model."""
        from magent.agraph.authoring import model_graph_draft

        config = registry_config(project)
        if config is None:
            _fail("No active user. Run `magent configure` first.", console)
        current = input_document(input_path) if input_path else None
        try:
            result = asyncio.run(model_graph_draft(goal, project=project, config=config, document=current, instruction=instruction))
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

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
        project: Path = typer.Option(Path("."), "--project", "-p"),
        agent: str = typer.Option("", "--agent", help="Preview this run-default OAP profile."),
    ) -> None:
        """Preview topology, routing tiers, gates, parallelism, and cost."""
        try:
            plan = plan_graph(path)
        except ValueError as exc:
            _fail(str(exc), console)
        if json_output:
            console.print_json(data=resolved_plan(path, project=str(project), config=registry_config(project), default_profile=agent))
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
        jsonl: bool = typer.Option(False, "--jsonl", help="Stream magent.graph-event.v1 JSON lines."),
        agent: str = typer.Option("", "--agent", help="Run graph agent nodes under an OAP profile."),
        execution_task_id: str = typer.Option("", "--execution-task-id", help="Attach the run to an existing durable task."),
        approve_gates: str = typer.Option("", "--approve-gates", help="Comma-separated reviewed gate node ids."),
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

        reviewed_gates = {item.strip() for item in approve_gates.split(",") if item.strip()}

        async def approve(prompt: str, detail: dict[str, Any]) -> bool:
            return yes or str(detail.get("node_id") or "") in reviewed_gates or Confirm.ask(prompt, default=False)

        config = load_config(username)
        effective_profile = _effective_profile(agent, project, config) if agent else None

        def emit(event: dict[str, Any]) -> None:
            if jsonl:
                console.print(json.dumps(event, separators=(",", ":"), default=str), markup=False)

        async def execute() -> dict[str, Any]:
            executor = GraphExecutor(username=username, config=config, project=project, store=store(), approval=approve, assume_yes=yes, profile=effective_profile, root_task_id=execution_task_id, event_sink=emit if jsonl else None)
            return await executor.run(path, params=params, dry_run=dry_run)

        try:
            result = asyncio.run(execute())
        except GraphRunError as exc:
            if jsonl:
                console.print(json.dumps({"schema_version": "magent.graph-event.v1", "type": "graph.error", "state": "failed", "error_code": exc.code, "error": str(exc)}, separators=(",", ":")), markup=False)
                raise typer.Exit(1) from exc
            _fail(str(exc), console)
        if jsonl:
            console.print(json.dumps({"schema_version": "magent.graph-result.v1", **result}, separators=(",", ":"), default=str), markup=False)
        elif json_output or dry_run:
            console.print_json(data=result)
        else:
            run = result["run"]
            style = "green" if result["ok"] else "red"
            console.print(f"[{style}]{run['status']}[/{style}] {run['run_id']} ({len(run['nodes'])} node records)")
            for item in run.get("diagnostics") or []:
                console.print(f"[yellow]{item['code']}[/yellow] {item['message']}")
            summary = run.get("summary") or {}
            console.print(f"Succeeded: {len(summary.get('succeeded') or [])} | Failed/blocked: {len(summary.get('failed') or [])} | Skipped: {len(summary.get('skipped') or [])}")
        if not result.get("ok"):
            raise typer.Exit(1)

    @graph_app.command("status")
    def status_cmd(
        run_id: str = typer.Argument(...),
        json_output: bool = typer.Option(False, "--json"),
        jsonl: bool = typer.Option(False, "--jsonl", help="Write lifecycle events as JSON lines."),
        event_limit: int = typer.Option(500, "--event-limit", min=1, max=5000),
    ) -> None:
        """Show a reconnectable graph status snapshot with job blockers and summaries."""
        from magent.agraph.status import graph_status

        result = graph_status(store(), run_id, event_limit=event_limit)
        if not result:
            _fail(f"Graph run not found: {run_id}", console)
        if jsonl:
            for event in result.get("events") or []:
                detail = event.get("detail") or {}
                if detail.get("schema_version") == "magent.graph-event.v1":
                    console.print(json.dumps(detail, separators=(",", ":"), default=str), markup=False)
            return
        if json_output:
            console.print_json(data=result)
            return
        table = Table(title=f"Graph run {run_id} · {result['state']}")
        table.add_column("Job")
        table.add_column("State")
        table.add_column("Profile")
        table.add_column("Summary / blocker")
        for node in result["nodes"]:
            blocker = "; ".join(item["message"] for item in node.get("blocked_by") or [])
            table.add_row(node["node_id"], node["state"], node["profile"] or "run-default", node["summary"] or blocker)
        console.print(table)

    @graph_app.command("resume")
    def resume_cmd(
        run_id: str = typer.Argument(...),
        path: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False),
        project: Path = typer.Option(Path("."), "--project", "-p"),
        force: bool = typer.Option(False, "--force"),
        yes: bool = typer.Option(False, "--yes"),
        execution_task_id: str = typer.Option("", "--execution-task-id"),
        approve_gates: str = typer.Option("", "--approve-gates"),
        retry_nodes: str = typer.Option("", "--retry-nodes", help="Comma-separated failed job ids to retry with their dependents."),
        json_output: bool = typer.Option(False, "--json"),
        jsonl: bool = typer.Option(False, "--jsonl"),
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

        reviewed_gates = {item.strip() for item in approve_gates.split(",") if item.strip()}

        async def approve(prompt: str, detail: dict[str, Any]) -> bool:
            return yes or str(detail.get("node_id") or "") in reviewed_gates or Confirm.ask(prompt, default=False)

        async def execute() -> dict[str, Any]:
            sink = (lambda event: console.print(json.dumps(event, separators=(",", ":"), default=str), markup=False)) if jsonl else None
            executor = GraphExecutor(username=username, config=load_config(username), project=project, store=store(), approval=approve, assume_yes=yes, root_task_id=execution_task_id, event_sink=sink)
            selected = {item.strip() for item in retry_nodes.split(",") if item.strip()}
            return await executor.run(graph_path, params=record.get("params") or {}, resume_record=record, force=force, retry_nodes=selected or None)

        result = asyncio.run(execute())
        if jsonl:
            console.print(json.dumps({"schema_version": "magent.graph-result.v1", **result}, separators=(",", ":"), default=str), markup=False)
        elif json_output:
            console.print_json(data=result)
        else:
            summary = result.get("run", {}).get("summary") or {}
            console.print(str(summary.get("text") or result.get("run", {}).get("status")))
        if not result.get("ok"):
            raise typer.Exit(1)


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
