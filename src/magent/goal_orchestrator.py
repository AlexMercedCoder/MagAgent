"""Opt-in staged goal orchestration.

The orchestrator keeps the existing goal loop as the default and adds a
durable, cacheable master-plan path for larger tasks. Each step packet is small
enough to hand to a sub-agent while preserving validation criteria and summary
requirements for the main agent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from magent.workbench import WorkbenchStore, build_plan, project_profile
from magent.workbench_store import now_iso


def create_orchestrated_goal(
    store: WorkbenchStore,
    goal: str,
    *,
    project: str | Path = ".",
    verify: bool = True,
    review: bool = True,
    max_steps: int = 3,
    planning_model_role: str = "review",
    execution_model_role: str = "coding",
    quiet: bool = False,
) -> dict[str, Any]:
    """Create a durable staged plan and cached step packets for a goal."""
    root = Path(project).resolve()
    profile = project_profile(root)
    steps = _build_steps(goal, profile, verify=verify, review=review, max_steps=max_steps)
    cache_key = _cache_key(goal, root, steps, planning_model_role, execution_model_role)
    master_plan = _render_master_plan(
        goal,
        root=root,
        profile=profile,
        steps=steps,
        cache_key=cache_key,
        planning_model_role=planning_model_role,
        execution_model_role=execution_model_role,
    )
    step_packets = [
        build_step_packet(
            goal=goal,
            root=root,
            cache_key=cache_key,
            steps=steps,
            step_index=index,
            planning_model_role=planning_model_role,
            execution_model_role=execution_model_role,
            completed_summaries=[],
        )
        for index, _step in enumerate(steps)
    ]
    goal_record = store.append(
        "goals",
        {
            "goal": goal,
            "project": str(root),
            "status": "planned",
            "mode": "orchestrated",
            "verify": verify,
            "review": review,
            "max_steps": len(steps),
            "planning_model_role": planning_model_role,
            "execution_model_role": execution_model_role,
            "cache_key": cache_key,
            "created_at": now_iso(),
        },
    )
    plan = store.append(
        "plans",
        {
            "goal": f"Orchestrated goal: {goal}",
            "root": str(root),
            "project": root.name,
            "status": "pending",
            "mode": "orchestrated-goal",
            "goal_id": goal_record["id"],
            "steps": [step["title"] for step in steps],
            "checks": _likely_checks(profile),
            "plan_markdown": master_plan,
            "orchestration": {
                "cache_key": cache_key,
                "planning_model_role": planning_model_role,
                "execution_model_role": execution_model_role,
                "steps": steps,
                "step_packets": step_packets,
                "completed_summaries": [],
                "current_step": 0,
                "status": "planned",
            },
        },
    )
    return {"ok": True, "goal": goal_record, "plan": plan, "orchestration": plan["orchestration"]}


async def run_orchestrated_goal(
    store: WorkbenchStore,
    goal: str,
    *,
    project: str | Path,
    username: str,
    provider: Any,
    extraction_provider: Any,
    config: Any,
    verify: bool = True,
    review: bool = True,
    max_steps: int = 3,
    planning_model_role: str = "review",
    execution_model_role: str = "coding",
    quiet: bool = False,
) -> dict[str, Any]:
    """Create and run a staged goal sequentially through sub-agents."""
    from magent.subagents import SubAgentRunner

    created = create_orchestrated_goal(
        store,
        goal,
        project=project,
        verify=verify,
        review=review,
        max_steps=max_steps,
        planning_model_role=planning_model_role,
        execution_model_role=execution_model_role,
    )
    plan = created["plan"]
    orchestration = plan["orchestration"]
    runner = SubAgentRunner(username, provider, extraction_provider, str(Path(project).resolve()), config, quiet=quiet)
    completed: list[dict[str, Any]] = []
    for index, step in enumerate(orchestration["steps"]):
        packet = build_step_packet(
            goal=goal,
            root=Path(project).resolve(),
            cache_key=orchestration["cache_key"],
            steps=orchestration["steps"],
            step_index=index,
            planning_model_role=planning_model_role,
            execution_model_role=execution_model_role,
            completed_summaries=completed,
        )
        store.update_item(
            "plans",
            plan["id"],
            orchestration={**orchestration, "current_step": index, "status": "running"},
        )
        task = await runner.spawn(f"{plan['id']}_step_{index + 1}", packet)
        summary = {
            "step": index + 1,
            "title": step["title"],
            "ok": not bool(task.error),
            "summary": task.result[:1600],
            "error": task.error,
            "completed_at": now_iso(),
        }
        completed.append(summary)
        if task.error:
            break
    status = "completed" if len(completed) == len(orchestration["steps"]) and all(item["ok"] for item in completed) else "blocked"
    final_orchestration = {
        **orchestration,
        "completed_summaries": completed,
        "current_step": len(completed),
        "status": status,
    }
    store.update_item("plans", plan["id"], status=status, orchestration=final_orchestration)
    store.update_item("goals", created["goal"]["id"], status=status)
    return {
        **created,
        "ok": status == "completed",
        "status": status,
        "orchestration": final_orchestration,
        "completed_summaries": completed,
    }


def build_step_packet(
    *,
    goal: str,
    root: Path,
    cache_key: str,
    steps: list[dict[str, Any]],
    step_index: int,
    planning_model_role: str,
    execution_model_role: str,
    completed_summaries: list[dict[str, Any]],
) -> str:
    """Return a compact, structured sub-agent packet for one step."""
    step = steps[step_index]
    completed_text = "\n".join(
        f"- Step {item['step']}: {item.get('summary') or item.get('error') or 'completed'}"
        for item in completed_summaries
    )
    return "\n".join(
        [
            f"MasterPlanCacheKey: {cache_key}",
            f"Goal: {goal}",
            f"ProjectRoot: {root}",
            f"PlanningModelRole: {planning_model_role}",
            f"ExecutionModelRole: {execution_model_role}",
            "",
            f"Step {step_index + 1} of {len(steps)}: {step['title']}",
            "",
            "Instructions:",
            *[f"- {item}" for item in step["instructions"]],
            "",
            "Validation Criteria:",
            *[f"- {item}" for item in step["validation"]],
            "",
            "Completed Prior Steps:",
            completed_text or "- None",
            "",
            "When done, summarize in this exact shape:",
            "Summary:",
            "- Files changed:",
            "- Commands run:",
            "- Validation evidence:",
            "- Blockers or residual risk:",
            "- Suggested memory candidates:",
        ]
    )


def _build_steps(goal: str, profile: dict[str, Any], *, verify: bool, review: bool, max_steps: int) -> list[dict[str, Any]]:
    steps = [
        {
            "title": "Orient to the project and refine scope",
            "instructions": [
                "Inspect the project profile, manifests, docs, and relevant files before editing.",
                "Confirm the target files or create the requested folder only if the goal requires it.",
                "Avoid broad refactors outside the goal.",
            ],
            "validation": [
                "Relevant project signals are identified.",
                "The next implementation surface is specific and bounded.",
            ],
        },
        {
            "title": "Implement the smallest complete change",
            "instructions": [
                "Use native file tools for edits and create complete non-placeholder artifacts.",
                "Prefer existing project conventions and dependency names from official package manifests.",
                "Keep the change focused on the measurable goal.",
            ],
            "validation": [
                "Requested files or behavior exist.",
                "Generated artifacts contain substantive content.",
                "No unrelated files are changed.",
            ],
        },
    ]
    if verify:
        steps.append(
            {
                "title": "Verify with project checks",
                "instructions": [
                    "Run the narrowest useful checks from the project profile or inferred commands.",
                    "If a command is missing, infer a conservative equivalent from project manifests.",
                    "Repair critical or medium failures before reporting success.",
                ],
                "validation": [
                    "At least one relevant check is run or a concrete blocker is explained.",
                    "Failures are summarized with command output evidence.",
                ],
            }
        )
    if review:
        steps.append(
            {
                "title": "Review and finalize",
                "instructions": [
                    "Review the final diff and artifacts with fresh context.",
                    "Flag correctness, safety, missing tests, docs drift, or UX issues.",
                    "Only loop on critical or medium issues; leave small polish as notes.",
                ],
                "validation": [
                    "No critical or medium review issues remain.",
                    "Final summary includes files changed, checks run, and residual risk.",
                ],
            }
        )
    if "doc" in goal.lower() or "readme" in goal.lower():
        steps.insert(
            -1 if verify or review else len(steps),
            {
                "title": "Update relevant documentation",
                "instructions": [
                    "Update README, packaged docs, and command references when user-facing behavior changes.",
                    "Keep CLI, GitHub, and desktop docs consistent.",
                ],
                "validation": [
                    "Docs mention the changed behavior or explain why no docs changed.",
                    "Generated command docs are refreshed if command help changed.",
                ],
            },
        )
    if not _likely_checks(profile):
        steps[0]["validation"].append("Missing project checks are explicitly noted.")
    return steps[: max(1, max_steps)]


def _render_master_plan(
    goal: str,
    *,
    root: Path,
    profile: dict[str, Any],
    steps: list[dict[str, Any]],
    cache_key: str,
    planning_model_role: str,
    execution_model_role: str,
) -> str:
    base_plan = build_plan(root, goal)
    lines = [
        f"# Orchestrated Goal: {goal}",
        "",
        f"Project: `{profile['name']}`",
        f"Root: `{root}`",
        f"Cache Key: `{cache_key}`",
        f"Planning Model Role: `{planning_model_role}`",
        f"Execution Model Role: `{execution_model_role}`",
        "",
        "## Cached Master Plan",
        base_plan,
        "",
        "## Staged Sub-Agent Steps",
    ]
    for index, step in enumerate(steps, start=1):
        lines.extend(
            [
                f"{index}. {step['title']}",
                "   Validation:",
                *[f"   - {item}" for item in step["validation"]],
            ]
        )
    lines.extend(
        [
            "",
            "## Replan Policy",
            "- Keep this master plan stable for prompt-cache reuse.",
            "- Replan only when validation reveals stale assumptions, missing dependencies, or a blocker.",
            "- Each sub-agent must return the requested compact summary so the main agent can launch the next step with minimal context.",
        ]
    )
    return "\n".join(lines)


def _likely_checks(profile: dict[str, Any]) -> list[str]:
    commands = profile.get("commands") if isinstance(profile, dict) else []
    if not isinstance(commands, list):
        return []
    return [str(command) for command in commands[:4] if str(command).strip()]


def _cache_key(goal: str, root: Path, steps: list[dict[str, Any]], planning_model_role: str, execution_model_role: str) -> str:
    payload = {
        "goal": goal,
        "root": str(root),
        "steps": [step["title"] for step in steps],
        "planning_model_role": planning_model_role,
        "execution_model_role": execution_model_role,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
