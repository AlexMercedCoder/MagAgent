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


def get_orchestrated_plan(store: WorkbenchStore, plan_id: str) -> dict[str, Any] | None:
    """Return a saved orchestrated plan by id."""
    for plan in store.read("plans", []):
        if plan.get("id") == plan_id and plan.get("mode") == "orchestrated-goal":
            return plan
    return None


def preview_orchestrated_plan(store: WorkbenchStore, plan_id: str, *, retry_step: int = 0) -> dict[str, Any]:
    """Return a dry-run preview for a saved orchestrated plan."""
    plan = get_orchestrated_plan(store, plan_id)
    if not plan:
        return {"ok": False, "error": f"Orchestrated plan not found: {plan_id}", "plan_id": plan_id}
    orchestration = _normalize_orchestration(plan)
    if orchestration.get("status") == "completed" and not retry_step:
        return {
            "ok": True,
            "status": "completed",
            "plan": plan,
            "orchestration": orchestration,
            "completed_summaries": orchestration.get("completed_summaries", []),
            "noop": True,
        }
    start_index = _start_index(orchestration, retry_step=retry_step)
    packet = build_step_packet(
        goal=_goal_text(plan),
        root=Path(plan.get("root") or ".").resolve(),
        cache_key=orchestration["cache_key"],
        steps=orchestration["steps"],
        step_index=start_index,
        planning_model_role=orchestration["planning_model_role"],
        execution_model_role=orchestration["execution_model_role"],
        completed_summaries=_prior_summaries(orchestration, start_index),
    )
    return {
        "ok": True,
        "plan": plan,
        "orchestration": orchestration,
        "next_step": start_index + 1,
        "retry_step": retry_step or None,
        "packet": packet,
    }


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
                "step_statuses": [
                    {"step": index + 1, "title": step["title"], "status": "pending"}
                    for index, step in enumerate(steps)
                ],
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
    run_result = await run_orchestrated_plan(
        store,
        created["plan"]["id"],
        username=username,
        provider=provider,
        extraction_provider=extraction_provider,
        config=config,
        quiet=quiet,
    )
    return {**created, **run_result, "plan": run_result.get("plan", created["plan"])}


async def run_orchestrated_plan(
    store: WorkbenchStore,
    plan_id: str,
    *,
    username: str,
    provider: Any,
    extraction_provider: Any,
    config: Any,
    retry_step: int = 0,
    quiet: bool = False,
) -> dict[str, Any]:
    """Resume or retry a saved orchestrated plan."""
    from magent.subagents import SubAgentRunner

    plan = get_orchestrated_plan(store, plan_id)
    if not plan:
        return {"ok": False, "error": f"Orchestrated plan not found: {plan_id}", "plan_id": plan_id}
    orchestration = _normalize_orchestration(plan)
    start_index = _start_index(orchestration, retry_step=retry_step)
    root = Path(plan.get("root") or ".").resolve()
    runner = SubAgentRunner(username, provider, extraction_provider, str(root), config, quiet=quiet)
    completed: list[dict[str, Any]] = _prior_summaries(orchestration, start_index)
    step_statuses = _step_statuses(orchestration)
    if retry_step:
        for status_item in step_statuses[start_index:]:
            status_item["status"] = "pending"
            status_item.pop("error", None)
            status_item.pop("completed_at", None)
    for index, step in enumerate(orchestration["steps"][start_index:], start=start_index):
        packet = build_step_packet(
            goal=_goal_text(plan),
            root=root,
            cache_key=orchestration["cache_key"],
            steps=orchestration["steps"],
            step_index=index,
            planning_model_role=orchestration["planning_model_role"],
            execution_model_role=orchestration["execution_model_role"],
            completed_summaries=completed,
        )
        step_statuses[index] = {
            **step_statuses[index],
            "status": "running",
            "started_at": now_iso(),
        }
        store.update_item(
            "plans",
            plan["id"],
            status="running",
            orchestration={
                **orchestration,
                "current_step": index,
                "status": "running",
                "step_statuses": step_statuses,
                "completed_summaries": completed,
            },
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
        step_statuses[index] = {
            **step_statuses[index],
            "status": "completed" if summary["ok"] else "failed",
            "ok": summary["ok"],
            "error": summary["error"],
            "completed_at": summary["completed_at"],
        }
        if task.error:
            break
    status = "completed" if len(completed) == len(orchestration["steps"]) and all(item["ok"] for item in completed) else "blocked"
    final_orchestration = {
        **orchestration,
        "completed_summaries": completed,
        "current_step": len(completed),
        "step_statuses": step_statuses,
        "status": status,
    }
    store.update_item("plans", plan["id"], status=status, orchestration=final_orchestration)
    updated_goal = None
    if plan.get("goal_id"):
        updated_goal = store.update_item("goals", plan["goal_id"], status=status)
    updated_plan = get_orchestrated_plan(store, plan_id) or {**plan, "status": status, "orchestration": final_orchestration}
    return {
        "ok": status == "completed",
        "status": status,
        "goal": updated_goal,
        "plan": updated_plan,
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


def _normalize_orchestration(plan: dict[str, Any]) -> dict[str, Any]:
    orchestration = dict(plan.get("orchestration") or {})
    steps = list(orchestration.get("steps") or [])
    completed = list(orchestration.get("completed_summaries") or [])
    orchestration.setdefault("cache_key", str(plan.get("cache_key") or ""))
    orchestration.setdefault("planning_model_role", str(plan.get("planning_model_role") or "review"))
    orchestration.setdefault("execution_model_role", str(plan.get("execution_model_role") or "coding"))
    orchestration["steps"] = steps
    orchestration.setdefault("step_packets", [])
    orchestration["completed_summaries"] = completed
    orchestration["current_step"] = int(orchestration.get("current_step") or len(completed))
    orchestration["status"] = str(orchestration.get("status") or plan.get("status") or "planned")
    orchestration["step_statuses"] = _step_statuses(orchestration)
    return orchestration


def _step_statuses(orchestration: dict[str, Any]) -> list[dict[str, Any]]:
    steps = list(orchestration.get("steps") or [])
    existing = list(orchestration.get("step_statuses") or [])
    statuses: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        current = existing[index] if index < len(existing) and isinstance(existing[index], dict) else {}
        statuses.append(
            {
                "step": index + 1,
                "title": step.get("title", f"Step {index + 1}"),
                "status": current.get("status") or "pending",
                **{k: v for k, v in current.items() if k not in {"step", "title", "status"}},
            }
        )
    return statuses


def _start_index(orchestration: dict[str, Any], *, retry_step: int = 0) -> int:
    steps = list(orchestration.get("steps") or [])
    if not steps:
        raise ValueError("Orchestrated plan has no steps")
    if retry_step:
        if retry_step < 1 or retry_step > len(steps):
            raise ValueError(f"retry_step must be between 1 and {len(steps)}")
        return retry_step - 1
    completed = [item for item in orchestration.get("completed_summaries", []) if item.get("ok")]
    return min(len(completed), len(steps) - 1)


def _prior_summaries(orchestration: dict[str, Any], start_index: int) -> list[dict[str, Any]]:
    summaries = list(orchestration.get("completed_summaries") or [])
    return [item for item in summaries if int(item.get("step") or 0) <= start_index]


def _goal_text(plan: dict[str, Any]) -> str:
    raw = str(plan.get("goal") or "")
    prefix = "Orchestrated goal: "
    return raw[len(prefix) :] if raw.startswith(prefix) else raw
