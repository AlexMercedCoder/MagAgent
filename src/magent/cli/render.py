"""Console rendering helpers for the CLI.

These ~13 `_print_*` functions were scattered through `cli/main.py`, which is
how a 4,900-line module stays 4,900 lines. They are presentation only: they
take already-computed data and write it to the console.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _print_research_result(result: dict) -> None:
    if not result.get("ok"):
        console.print(f"[red]Research failed:[/red] {result.get('error', 'unknown error')}")
        return
    from rich.markdown import Markdown

    console.print(Panel.fit(f"[bold]{result.get('topic', 'Research')}[/bold]", title="Research"))
    summary = str(result.get("summary") or "").strip()
    if summary:
        console.print(Markdown(summary))
    sources = result.get("sources") or []
    if sources:
        table = Table("Source", "Title", "URL")
        for index, source in enumerate(sources, start=1):
            table.add_row(
                str(index),
                str(source.get("title") or "Untitled")[:80],
                str(source.get("url") or "")[:100],
            )
        console.print(table)

def _print_session_usage(data: dict) -> None:
    if not data.get("ok"):
        console.print("[dim]No session log found yet.[/dim]")
        return
    table = Table("Metric", "Value")
    for key in ("turns", "tool_calls", "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
        table.add_row(key.replace("_", " ").title(), str(data.get(key, 0)))
    table.add_row("Estimated Cost", f"${float(data.get('cost_usd') or 0):.6f}")
    console.print(table)
    slowest = data.get("slowest") or []
    if slowest:
        slow_table = Table("Slow Step", "Duration", "Detail")
        for item in slowest[:5]:
            duration = float(item.get("duration_ms") or 0)
            metadata = item.get("metadata") or {}
            detail = str(metadata.get("description") or metadata.get("path") or metadata.get("tool") or "")[:80]
            slow_table.add_row(str(item.get("name") or ""), f"{duration / 1000:.1f}s", detail)
        console.print(slow_table)

def _print_recent_insights(data: dict) -> None:
    totals = data.get("totals") or {}
    console.print(
        Panel(
            "\n".join(
                [
                    f"Sessions: {totals.get('sessions', 0)}",
                    f"Turns: {totals.get('turns', 0)}",
                    f"Tool calls: {totals.get('tool_calls', 0)}",
                    f"Tokens: {totals.get('total_tokens', 0)}",
                    f"Cached tokens: {totals.get('cached_tokens', 0)}",
                    f"Estimated cost: ${float(totals.get('cost_usd') or 0):.6f}",
                ]
            ),
            title="Recent Session Insights",
        )
    )
    rows = data.get("sessions") or []
    if rows:
        table = Table("Session Log", "Turns", "Tools", "Tokens", "Slowest")
        for item in rows:
            slowest = (item.get("slowest") or [{}])[0]
            table.add_row(
                Path(str(item.get("path") or "")).name,
                str(item.get("turns", 0)),
                str(item.get("tool_calls", 0)),
                str(item.get("total_tokens", 0)),
                str(slowest.get("name") or ""),
            )
        console.print(table)

def _print_session_peers(peers: list[dict]) -> None:
    if not peers:
        console.print("[dim]No other live local sessions.[/dim]")
        return
    table = Table("Session ID", "Name", "Project", "Policy", "PID", "State")
    for peer in peers:
        table.add_row(
            str(peer.get("session_id") or ""),
            str(peer.get("name") or ""),
            str(peer.get("project") or ""),
            str(peer.get("policy") or ""),
            str(peer.get("pid") or ""),
            "live" if peer.get("live", True) else "stale",
        )
    console.print(table)

def _print_session_receipt(result: dict) -> None:
    color = "green" if result.get("ok") else "yellow"
    console.print(
        f"[{color}]{result.get('status', 'unknown')}[/{color}] "
        f"message {result.get('message_id', '')} to {result.get('target_id', '')}"
    )
    if result.get("reason"):
        console.print(f"[dim]{result['reason']}[/dim]")
    if result.get("cross_project"):
        console.print(
            f"[yellow]Cross-project delivery:[/yellow] "
            f"{result.get('source_project')} -> {result.get('target_project')}. "
            "Check worktree ownership before editing shared files."
        )

def _print_session_inbox(items: list[dict], *, held: bool = False) -> None:
    if not items:
        label = "held" if held else "accepted"
        console.print(f"[dim]No {label} peer messages.[/dim]")
        return
    table = Table("Message ID", "From", "Project", "Received", "Message")
    for item in items:
        table.add_row(
            str(item.get("message_id") or ""),
            str(item.get("sender_name") or item.get("sender_id") or ""),
            str(item.get("project") or ""),
            str(item.get("received_at") or "")[:19],
            str(item.get("message") or "")[:100],
        )
    console.print(table)

def _print_session_receipts(items: list[dict]) -> None:
    if not items:
        console.print("[dim]No delivery receipts for this session.[/dim]")
        return
    table = Table("Time", "Message ID", "Target", "Status", "Reason")
    for item in items:
        table.add_row(
            str(item.get("ts") or "")[:19],
            str(item.get("message_id") or ""),
            str(item.get("target_id") or ""),
            str(item.get("status") or ""),
            str(item.get("reason") or "")[:80],
        )
    console.print(table)

def _print_context_map(data: dict) -> None:
    console.print(Panel.fit(f"[bold]{data.get('project', '')}[/bold]", title="Context Map"))
    workspace = data.get("workspace") or {}
    doctor = data.get("project_doctor") or {}
    memory = data.get("memory") or {}
    table = Table("Area", "Signal")
    table.add_row("Git", f"{len(workspace.get('git_status') or [])} status entries")
    table.add_row("Plans", str(workspace.get("pending_plans", 0)))
    table.add_row("Patches", str(workspace.get("patches", 0)))
    table.add_row("Checkpoints", str(workspace.get("checkpoint_sessions", 0)))
    missing = doctor.get("missing") or []
    table.add_row("Project doctor", "ok" if doctor.get("ok") else f"missing: {', '.join(missing[:4]) or 'none'}")
    stats = memory.get("stats") or {}
    table.add_row("Memory", f"{stats.get('nodes', 0)} nodes" if memory.get("available") else "unavailable")
    console.print(table)

    plans = (data.get("active_workbench") or {}).get("plans") or []
    if plans:
        plan_table = Table("ID", "Status", "Mode", "Goal")
        for plan in plans[:5]:
            plan_table.add_row(
                plan.get("id", ""),
                plan.get("status", ""),
                plan.get("mode", "draft"),
                str(plan.get("goal", ""))[:80],
            )
        console.print(plan_table)

    candidates = data.get("promotion_candidates") or []
    if candidates:
        cand_table = Table("Memory Candidate", "Source", "Title")
        for item in candidates[:8]:
            cand_table.add_row(
                item.get("id", ""),
                item.get("source", ""),
                str(item.get("title", ""))[:80],
            )
        console.print(cand_table)
    else:
        console.print("[dim]No high-value memory promotion candidates right now.[/dim]")

    recall = (memory.get("recall") or "").strip()
    if recall:
        console.print(Panel(recall, title="Memory Recall"))

def _print_jobs_summary(data: dict) -> None:
    counts = data.get("counts") or {}
    title = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items())) or "no jobs"
    console.print(Panel.fit(title, title="Background Jobs"))
    table = Table("ID", "Status", "Kind", "Project", "Payload")
    for item in (data.get("jobs") or [])[:20]:
        payload = item.get("payload") or {}
        table.add_row(
            item.get("id", ""),
            item.get("status", ""),
            item.get("kind", ""),
            Path(item.get("project", ".")).name,
            json.dumps(payload)[:90],
        )
    console.print(table)

def _print_orchestrated_preview(data: dict) -> None:
    plan = data.get("plan") or {}
    orchestration = data.get("orchestration") or {}
    console.print(Panel(plan.get("plan_markdown", ""), title=f"Orchestrated Plan {plan.get('id', '')}"))
    table = Table("Step", "Status", "Title")
    for item in orchestration.get("step_statuses") or []:
        table.add_row(str(item.get("step", "")), str(item.get("status", "")), str(item.get("title", ""))[:80])
    console.print(table)
    console.print(Panel(data.get("packet", ""), title=f"Next Step Packet {data.get('next_step')}"))

def _print_orchestrated_run_result(data: dict) -> None:
    plan = data.get("plan") or {}
    orchestration = data.get("orchestration") or {}
    status = data.get("status") or orchestration.get("status") or "unknown"
    console.print(Panel.fit(f"[bold]{plan.get('id', '')}[/bold] {status}", title="Orchestrated Goal"))
    table = Table("Step", "Status", "Title", "Evidence")
    summaries = {int(item.get("step") or 0): item for item in data.get("completed_summaries") or []}
    for item in orchestration.get("step_statuses") or []:
        step_no = int(item.get("step") or 0)
        summary = summaries.get(step_no, {})
        evidence = summary.get("error") or summary.get("summary") or ""
        table.add_row(
            str(step_no),
            str(item.get("status", "")),
            str(item.get("title", ""))[:60],
            str(evidence).replace("\n", " ")[:90],
        )
    console.print(table)
    if not data.get("ok"):
        console.print("[yellow]Resume with `magent goal-run <plan-id>` or retry a failed step with `magent goal-run <plan-id> --retry-step N`.[/yellow]")

def _print_config_center(config, provider_display: str = "") -> None:
    console.print(Panel.fit("[bold]MagAgent Config[/bold]", title="Control Center"))
    table = Table("Area", "Current", "Command")
    table.add_row(
        "Provider",
        f"{config.default_provider}/{config.default_model}",
        "magent provider wizard",
    )
    table.add_row(
        "Model roles",
        ", ".join(f"{role}:{value or '-'}" for role, value in config.model_roles.items()),
        "magent model wizard",
    )
    table.add_row("Permissions", config.permission_mode, "magent permission set <mode>")
    table.add_row(
        "Memory",
        f"write every {config.write_every_n_turns} turns",
        "magent memory configure",
    )
    table.add_row(
        "Subagents",
        f"max {config.max_subagents}, parallel {config.max_parallel_subagents}",
        "magent subagent wizard",
    )
    table.add_row("Tools", "capability packs", "magent tools list")
    table.add_row("Context", "audit active context", "magent context audit")
    if provider_display:
        table.add_row("Session provider", provider_display, "magent model")
    console.print(table)

def _print_memory_stats(stats: dict, username: str):
    from magent.utils import human_bytes

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Key", style="dim")
    t.add_column("Value", style="bold")

    t.add_row("Nodes", str(stats.get("nodes", 0)))
    t.add_row("Edges", str(stats.get("edges_total", 0)))

    nt = stats.get("node_types", {})
    for ntype, count in sorted(nt.items(), key=lambda x: -x[1]):
        t.add_row(f"  {ntype}", str(count))

    t.add_row("", "")
    t.add_row("Graph disk", human_bytes(stats.get("disk_bytes", 0)))
    t.add_row("Avg node size", human_bytes(stats.get("avg_node_bytes", 0)))
    t.add_row("Largest node", human_bytes(stats.get("largest_node_bytes", 0)))
    t.add_row("Git commits", str(stats.get("git_commits", "n/a")))
    t.add_row("Last modified", str(stats.get("last_modified", "n/a")))

    console.print(Panel(t, title=f"[bold cyan]Memory Graph — {username}[/bold cyan]"))
