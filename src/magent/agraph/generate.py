"""Generate reviewable, conformant AGS documents from goals and saved plans."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from magent.agraph.document import write_graph
from magent.agraph.validate import ValidationReport, validate_graph
from magent.project_scan import scan_estimate
from magent.repo_map import RepoMapCache


def generate_graph_document(goal: str, *, project: str | Path = ".") -> dict[str, Any]:
    """Create a conservative two-stage graph skeleton with per-node contracts."""
    title = goal.strip().rstrip(".")[:180] or "Complete project goal"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "generated-goal"
    root = Path(project).expanduser().resolve()
    context = {
        "project": str(root),
        "project_scan": scan_estimate(root, limit=2000),
        "repository_map": RepoMapCache(root, max_files=500).relevant_slice(
            title, max_tokens=1200
        ),
    }
    nodes = {
        "inspect": {
            "type": "task",
            "title": "Inspect the project and define the change",
            "description": f"Inspect the project for this objective: {title}. Identify relevant files, constraints, existing tests, and a focused implementation approach. Do not edit files.",
            "inputs": {
                "project_scan": {
                    "type": "object",
                    "description": "Bounded project size and freshness summary.",
                    "from": "context.project_scan",
                },
                "repository_map": {
                    "type": "markdown",
                    "description": "Token-bounded files and symbols relevant to the goal.",
                    "from": "context.repository_map",
                },
            },
            "outputs": {"findings": {"type": "markdown", "description": "Focused project findings and implementation approach."}},
            "intelligence": {"tier": "standard", "hints": ["code_comprehension"], "rationale": "Bounded project inspection."},
            "requirements": {"tools": ["file_read", "file_search"], "permissions": ["fs:read:**"], "workspace": "read_only"},
            "constraints": {"max_agent_steps": 16, "max_wall_clock_seconds": 900},
            "failure": {"retry": {"max_attempts": 2, "retry_on": ["transient", "criteria_failed"]}, "on_exhausted": "fail"},
            "success": {"summary": "A concrete implementation approach exists.", "criteria": [{"id": "findings_present", "kind": "artifact_present", "description": "Inspection findings were emitted.", "output": "findings"}]},
            "estimate": {"effort": "s", "cost_usd": 0.2},
        },
        "implement": {
            "type": "task",
            "title": "Implement the objective",
            "description": f"Implement this objective completely and narrowly: {title}. Follow the inspection findings, existing project conventions, and update tests and documentation when behavior changes.",
            "depends_on": ["inspect"],
            "inputs": {"approach": {"type": "markdown", "description": "Inspection findings.", "from": "nodes.inspect.outputs.findings"}},
            "outputs": {"summary": {"type": "markdown", "description": "Implemented changes and affected files."}},
            "intelligence": {"tier": "advanced", "hints": ["code_generation", "precision_critical"], "rationale": "Implementation requires project-aware edits and verification."},
            "requirements": {"tools": ["file_read", "file_search", "file_write", "shell_exec"], "permissions": ["fs:read:**", "fs:write:**", "shell:exec:*"], "workspace": "read_write"},
            "constraints": {"max_agent_steps": 40, "max_wall_clock_seconds": 1800},
            "failure": {"retry": {"max_attempts": 2, "retry_on": ["transient", "tool_error", "criteria_failed"], "feedback": "failed_criteria"}, "on_exhausted": "fail"},
            "success": {"summary": "The objective is implemented and summarized.", "criteria": [{"id": "summary_present", "kind": "artifact_present", "description": "The implementation summary was emitted.", "output": "summary"}]},
            "estimate": {"effort": "m", "cost_usd": 1.5},
        },
        "verify": {
            "type": "task",
            "title": "Verify and review the result",
            "description": "Run the narrowest relevant checks, inspect the resulting diff, repair issues found, and report evidence that the objective is complete.",
            "depends_on": ["implement"],
            "inputs": {"changes": {"type": "markdown", "description": "Implementation summary.", "from": "nodes.implement.outputs.summary"}},
            "outputs": {"report": {"type": "markdown", "description": "Checks run, results, residual risks, and completion assessment."}},
            "intelligence": {"tier": "advanced", "hints": ["adversarial_review", "code_comprehension"], "rationale": "Fresh-context verification protects against implementation blind spots."},
            "requirements": {"tools": ["file_read", "file_search", "file_write", "shell_exec"], "permissions": ["fs:read:**", "fs:write:**", "shell:exec:*"], "workspace": "read_write"},
            "constraints": {"max_agent_steps": 30, "max_wall_clock_seconds": 1800},
            "failure": {"retry": {"max_attempts": 2, "retry_on": ["transient", "criteria_failed"], "feedback": "failed_criteria"}, "on_exhausted": "fail"},
            "success": {"summary": "Verification evidence supports completion.", "criteria": [{"id": "report_present", "kind": "artifact_present", "description": "A verification report was emitted.", "output": "report"}]},
            "estimate": {"effort": "m", "cost_usd": 0.8},
        },
    }
    return {
        "ags_version": "1.0",
        "kind": "AgenticGraph",
        "id": f"magent/generated/{slug}",
        "title": title,
        "objective": goal.strip(),
        "version": "1.0.0",
        "requires_conformance": 2,
        "authors": [{"name": "MagAgent", "role": "generator"}],
        "context": context,
        "constraints": {"max_parallel_nodes": 1, "max_node_executions": 10, "max_wall_clock_seconds": 7200, "max_cost_usd": 10.0},
        "policy": {"on_expression_error": "fail", "on_node_failure": "halt", "checkpointing": "per_node"},
        "entrypoints": ["inspect"],
        "nodes": nodes,
        "outputs": {"verification_report": {"type": "markdown", "description": "Final verification evidence.", "from": "nodes.verify.outputs.report"}},
    }


def generate_and_validate(goal: str, *, project: str | Path = ".", strict: bool = True) -> tuple[dict[str, Any], ValidationReport]:
    graph = generate_graph_document(goal, project=project)
    return graph, validate_graph(graph, strict=strict)


def generate_to_file(goal: str, output: str | Path, *, project: str | Path = ".") -> tuple[Path, ValidationReport]:
    graph, report = generate_and_validate(goal, project=project)
    if not report.ok:
        return Path(output), report
    return write_graph(graph, output), report


def plan_record_to_graph(plan: dict[str, Any]) -> dict[str, Any]:
    goal = str(plan.get("goal") or plan.get("title") or "Complete saved plan")
    graph = generate_graph_document(goal, project=plan.get("root", "."))
    commands = [str(item) for item in plan.get("checks") or plan.get("commands") or [] if str(item).strip()]
    if commands:
        graph["context"]["recommended_checks"] = commands
        graph["nodes"]["verify"]["description"] += " Recommended checks: " + "; ".join(commands)
    graph["metadata"] = {"source": "magent-plan", "source_plan_id": plan.get("id", "")}
    return graph
