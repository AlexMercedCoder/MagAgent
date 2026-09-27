"""Per-run memory evidence: which MagGraph nodes a run actually used.

Recalled memory used to reach the prompt as plain text with nothing recorded
about which nodes it came from, so a run could not show what it remembered.
Every turn that assembles context now produces one evidence record. The
records travel with the run: the durable execution task
(``metadata.memory_evidence``), ``magent ask --json``, the Web UI run center,
``/why last`` and ``magent memory evidence``.

Record shape (``magent.memory-evidence.v1``)::

    {
      "schema": "magent.memory-evidence.v1",
      "turn": 1,
      "recorded_at": "2026-09-27T12:00:00+00:00",
      "status": "used" | "no_match" | "unavailable" | "blocked_by_profile",
      "query_preview": "first 160 characters of the user message",
      "nodes": [{"id", "type", "score", "matched", "reason", "source"}],
      "tokens": {"recalled": 812, "injected": 640, "budget": 4000, "profile_reserve": 1200},
      "truncated": true,
      "truncation": ["recall_budget", "profile_reserve"]
    }

``source`` is ``personal`` or ``team`` (reviewed team memory). ``tokens`` are estimates (about four characters per token), the same
estimator the context budget uses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

EVIDENCE_SCHEMA = "magent.memory-evidence.v1"
RUN_EVIDENCE_SCHEMA = "magent.run-memory-evidence.v1"
QUERY_PREVIEW_CHARS = 160
MAX_TURNS_PER_RUN = 200

STATUSES = ("used", "no_match", "unavailable", "blocked_by_profile")


def build_turn_evidence(
    *,
    turn: int,
    status: str,
    query: str = "",
    recall: dict[str, Any] | None = None,
    injected_tokens: int = 0,
    budget_tokens: int = 0,
    profile_reserve_tokens: int = 0,
    profile_truncated: bool = False,
) -> dict[str, Any]:
    """Build one turn's evidence record from a recall result."""

    if status not in STATUSES:
        raise ValueError(f"unknown memory evidence status: {status}")
    recall = recall or {}
    truncation: list[str] = []
    if recall.get("truncated"):
        truncation.append("recall_budget")
    if profile_truncated:
        truncation.append("profile_reserve")
    preview = " ".join(str(query or "").split())
    if len(preview) > QUERY_PREVIEW_CHARS:
        preview = preview[: QUERY_PREVIEW_CHARS - 1].rstrip() + "…"
    return {
        "schema": EVIDENCE_SCHEMA,
        "turn": int(turn),
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": status,
        "query_preview": preview,
        "nodes": [dict(node) for node in recall.get("nodes", [])] if status == "used" else [],
        "tokens": {
            "recalled": int(recall.get("tokens", 0) or 0) if status == "used" else 0,
            "injected": int(injected_tokens) if status == "used" else 0,
            "budget": int(budget_tokens),
            "profile_reserve": int(profile_reserve_tokens),
        },
        "truncated": bool(truncation),
        "truncation": truncation,
    }


def summarize(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a run's per-turn records into one summary."""

    unique: list[str] = []
    for record in turns:
        for node in record.get("nodes", []):
            node_id = str(node.get("id") or "")
            if node_id and node_id not in unique:
                unique.append(node_id)
    return {
        "turns": len(turns),
        "turns_with_memory": sum(1 for record in turns if record.get("status") == "used"),
        "unique_nodes": unique,
        "tokens_injected": sum(
            int(record.get("tokens", {}).get("injected", 0)) for record in turns
        ),
        "truncated": any(record.get("truncated") for record in turns),
    }


def run_evidence_payload(
    turns: list[dict[str, Any]],
    *,
    source: str,
    task: dict[str, Any] | None = None,
    run_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """The machine-facing envelope shared by CLI, desktop and Web UI callers."""

    task = task or {}
    metadata = task.get("metadata") or {}
    return {
        "ok": True,
        "schema": RUN_EVIDENCE_SCHEMA,
        "source": source,
        "task_id": str(task.get("id") or ""),
        "run_id": run_id,
        "session_id": session_id or str(task.get("session_id") or ""),
        "title": str(task.get("title") or ""),
        "state": str(task.get("state") or ""),
        "provider": str(metadata.get("provider") or ""),
        "model": str(metadata.get("model") or ""),
        "updated_at": str(task.get("updated_at") or ""),
        "turns": list(turns),
        "summary": summarize(turns),
    }


def task_memory_evidence(
    username: str,
    task_id: str = "",
    *,
    search_limit: int = 200,
) -> dict[str, Any]:
    """Return memory evidence for one execution task, or the latest that has any.

    ``task_id`` of ``""`` or ``"last"`` selects the most recent task whose
    record carries memory evidence.
    """

    from magent.task_runtime import TaskRuntime
    from magent.workbench_store import WorkbenchStore

    runtime = TaskRuntime(WorkbenchStore(username))
    wanted = "" if task_id in {"", "last"} else task_id
    if wanted:
        task = runtime.get(wanted)
        if task is None:
            return {
                "ok": False,
                "schema": RUN_EVIDENCE_SCHEMA,
                "error": f"No execution task called {wanted}.",
                "hint": "List tasks with `magent execution list`.",
            }
        turns = list((task.get("metadata") or {}).get("memory_evidence") or [])
        return run_evidence_payload(turns, source="task", task=task)
    for candidate in runtime.list_tasks(limit=search_limit):
        recorded = (candidate.get("metadata") or {}).get("memory_evidence")
        if recorded:
            return run_evidence_payload(list(recorded), source="task", task=candidate)
    return {
        "ok": False,
        "schema": RUN_EVIDENCE_SCHEMA,
        "error": "No recorded run has memory evidence yet.",
        "hint": "Runs record which memories they used from MagAgent 1.4 on. "
        'Try `magent ask "..."`, then `magent memory evidence last`.',
    }


def render_lines(payload: dict[str, Any]) -> list[str]:
    """Plain-text explanation used by `/why last` and `magent memory evidence`."""

    turns = payload.get("turns") or []
    summary = payload.get("summary") or summarize(turns)
    heading = payload.get("title") or payload.get("task_id") or payload.get("run_id") or "this run"
    lines = [
        f"Memory used by {heading}: {summary['turns_with_memory']} of {summary['turns']} "
        f"turn(s) recalled memory, {len(summary['unique_nodes'])} node(s), "
        f"~{summary['tokens_injected']} tokens injected"
        + (" (truncated)" if summary["truncated"] else "")
    ]
    for record in turns:
        status = record.get("status", "")
        tokens = record.get("tokens", {})
        prefix = f"turn {record.get('turn', '?')}"
        if status != "used":
            label = {
                "no_match": "no memory matched",
                "unavailable": "memory graph unavailable",
                "blocked_by_profile": "the agent profile does not allow memory reads",
            }.get(status, status)
            lines.append(f"  {prefix}: {label}")
            continue
        truncation = ", ".join(record.get("truncation") or [])
        lines.append(
            f"  {prefix}: {len(record.get('nodes', []))} node(s), ~{tokens.get('injected', 0)}"
            f"/{tokens.get('budget', 0)} tokens"
            + (f", truncated by {truncation}" if truncation else "")
        )
        for node in record.get("nodes", []):
            matched = ", ".join(node.get("matched") or []) or "graph search"
            score = node.get("score")
            score_text = f"score {score:g}" if isinstance(score, int | float) else "no score"
            lines.append(f"    - {node.get('id')} ({score_text}; matched {matched})")
    return lines
