"""Daily-driver UX helpers for goal loops, jobs, context, and statuslines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magent.daemon import enqueue_task, list_queue
from magent.workbench_store import now_iso


def create_goal(
    store: Any,
    goal: str,
    *,
    project: str | Path = ".",
    verify: bool = True,
    review: bool = True,
    background: bool = False,
    max_loops: int = 3,
    verifier_model: str = "cheap",
    reviewer_model: str = "review",
) -> dict[str, Any]:
    """Create a durable goal-loop record and optional background task."""
    root = Path(project).resolve()
    instructions = build_goal_prompt(
        goal,
        verify=verify,
        review=review,
        max_loops=max_loops,
        verifier_model=verifier_model,
        reviewer_model=reviewer_model,
    )
    record = store.append(
        "goals",
        {
            "goal": goal,
            "project": str(root),
            "status": "queued" if background else "planned",
            "verify": verify,
            "review": review,
            "max_loops": max_loops,
            "verifier_model": verifier_model,
            "reviewer_model": reviewer_model,
            "prompt": instructions,
            "created_at": now_iso(),
        },
    )

    from magent.workbench_domains.plans import save_execution_plan

    commands = ["magent project doctor", "magent release check"]
    if verify:
        commands.append("magent recipe run verify-and-review")
    plan = save_execution_plan(store, root, f"Goal loop: {goal}", commands=commands, include_diff=False)
    store.update_item("plans", plan["id"], status="pending", goal_id=record["id"], mode="goal-loop")
    queued = None
    if background:
        queued = enqueue_task(
            store,
            "ask",
            {"task": instructions, "source": f"goal/{record['id']}"},
            project=root,
        )
    return {"ok": True, "goal": record, "plan": plan, "queued": queued}


def build_goal_prompt(
    goal: str,
    *,
    verify: bool = True,
    review: bool = True,
    max_loops: int = 3,
    verifier_model: str = "cheap",
    reviewer_model: str = "review",
) -> str:
    """Return an agent prompt for measurable implement/verify/review loops."""
    lines = [
        f"Goal: {goal}",
        "",
        f"Continue until the measurable goal is complete or {max_loops} implement/verify/review loops have run.",
        "Use native file tools for edits and run the narrowest useful checks after each implementation pass.",
        "If the goal asks for a new folder, create and work in that new folder; do not accidentally continue inside an existing sibling project unless asked.",
        "Before installing dependencies, inspect the target framework's expected package names and use the canonical package name. Example: Astro/AstroJS projects install the npm package `astro`, not `astrojs`.",
        "For generated files, use one complete `write_file` call per file with both `path` and full `content`. If a write fails due to missing content, immediately retry with complete content before doing more research.",
    ]
    if verify:
        lines.extend(
            [
                "",
                "Verifier loop:",
                f"- Spawn or emulate a verifier subagent using the `{verifier_model}` model role when available.",
                "- Build/test/lint the project using configured project commands.",
                "- If no project commands are configured, infer the likely checks from package files; for Astro projects run install if needed and then `npm run build`.",
                "- For UI work, use browser automation or screenshots when available.",
                "- Return critical and medium issues to the main agent for repair.",
            ]
        )
    if review:
        lines.extend(
            [
                "",
                "Reviewer loop:",
                f"- After verification passes, spawn or emulate a reviewer subagent using the `{reviewer_model}` model role when available.",
                "- Review the diff with fresh context for correctness, robustness, project standards, and missing tests.",
                "- Continue only on critical or medium issues; leave small polish notes for the human.",
            ]
        )
    lines.extend(
        [
            "",
            "Stop condition:",
            "- The goal is implemented.",
            "- Verification passes or the remaining blocker is clearly explained.",
            "- Every requested file exists and has non-placeholder content.",
            "- Review finds no critical or medium issues.",
            "- Final response summarizes files changed, checks run, and any residual risk.",
        ]
    )
    return "\n".join(lines)


def jobs_summary(store: Any, *, status: str = "") -> dict[str, Any]:
    """Return friendly background-job summary data."""
    queue = list_queue(store, status=status).get("tasks", [])
    counts: dict[str, int] = {}
    for item in queue:
        key = str(item.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {"ok": True, "counts": counts, "jobs": queue}


def statusline_data(config: Any, *, username: str, cwd: str | Path, store: Any) -> dict[str, Any]:
    """Return configurable statusline fields for shell integrations."""
    root = Path(cwd).resolve()
    queue = list_queue(store).get("tasks", [])
    pending_jobs = sum(1 for item in queue if item.get("status") in {"pending", "running"})
    branch = _git_branch(root)
    return {
        "ok": True,
        "user": username,
        "provider": getattr(config, "default_provider", ""),
        "model": getattr(config, "default_model", ""),
        "mode": getattr(config, "permission_mode", ""),
        "project": root.name,
        "cwd": str(root),
        "branch": branch,
        "pending_jobs": pending_jobs,
        "max_subagents": getattr(config, "max_subagents", 0),
    }


def render_statusline(data: dict[str, Any], template: str = "") -> str:
    """Render a compact statusline from a payload."""
    if not template:
        template = "{project} {branch} | {provider}/{model} | {mode} | jobs:{pending_jobs} | sub:{max_subagents}"
    safe = {key: "" if value is None else value for key, value in data.items()}
    try:
        return template.format(**safe)
    except KeyError:
        return template


def context_audit(data: dict[str, Any]) -> dict[str, Any]:
    """Return actionable context-hygiene suggestions from a context map."""
    suggestions: list[str] = []
    workspace = data.get("workspace") or {}
    doctor = data.get("project_doctor") or {}
    active = data.get("active_workbench") or {}
    memory = data.get("memory") or {}
    playbook = data.get("playbook") or {}
    if not playbook.get("exists"):
        suggestions.append("Run `magent project init` to create .magent/playbook.toml for project commands.")
    if doctor.get("missing"):
        suggestions.append("Configure missing project command roles with `magent project command-promote` or .magent/playbook.toml.")
    if (workspace.get("pending_plans") or 0) > 3:
        suggestions.append("Review old draft plans with `magent plan-list` and discard stale ones.")
    if active.get("failed_commands"):
        suggestions.append("Promote recurring command failures with `magent memory inbox` after triage.")
    if memory.get("available") and not (memory.get("recall") or "").strip():
        suggestions.append("Use `/context <topic>` or `magent context map --query <topic>` before large tasks.")
    if not suggestions:
        suggestions.append("Context looks lean. Use `/clear` before switching to an unrelated task.")
    return {"ok": True, "suggestions": suggestions, "data": data}


def _git_branch(root: Path) -> str:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return ""
