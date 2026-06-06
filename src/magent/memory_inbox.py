"""Interactive inbox for reviewing memory promotion candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magent.context import promotion_candidates
from magent.hooks import run_hooks
from magent.records import PromotionCandidateRecord
from magent.workbench import session_timeline
from magent.workbench_store import now_iso

DECISION_STORE = "memory_inbox_decisions"


def memory_inbox(store: Any, project: str | Path = ".", limit: int = 30) -> dict[str, Any]:
    """Return pending memory candidates with accept/reject/edit state applied."""
    decisions = _decisions_by_id(store)
    candidates = []
    for candidate in promotion_candidates(store, project, limit=limit):
        run_hooks(project, "memory_candidate", {"candidate": candidate})
        decision = decisions.get(candidate["id"], {})
        status = decision.get("status", "pending")
        if status == "rejected":
            continue
        candidates.append(_merge_decision(candidate, decision))
    for event in _session_candidates(limit=5):
        decision = decisions.get(event["id"], {})
        if decision.get("status") == "rejected":
            continue
        candidates.append(_merge_decision(event, decision))
    return {"ok": True, "project": str(Path(project).resolve()), "candidates": candidates[:limit]}


def accept_candidate(store: Any, memory_manager: Any, candidate_id: str, project: str | Path = ".") -> dict[str, Any]:
    """Write a pending inbox candidate to MagGraph memory."""
    candidate = find_candidate(store, candidate_id, project)
    if not candidate:
        return {"ok": False, "error": f"Memory inbox candidate not found: {candidate_id}"}
    record = PromotionCandidateRecord.from_mapping(candidate)
    written = memory_manager.write_memories(
        [record.to_memory_item()],
        project_slug=_slug(Path(project).resolve().name),
    )
    _record_decision(store, candidate_id, status="accepted", written=written)
    return {"ok": written > 0, "written": written, "candidate": record.to_memory_item()}


def reject_candidate(store: Any, candidate_id: str, reason: str = "") -> dict[str, Any]:
    """Reject a pending inbox candidate."""
    item = _record_decision(store, candidate_id, status="rejected", reason=reason)
    return {"ok": True, "decision": item}


def edit_candidate(store: Any, candidate_id: str, body: str, title: str = "") -> dict[str, Any]:
    """Store edited candidate text before acceptance."""
    updates: dict[str, Any] = {"status": "edited", "body": body}
    if title:
        updates["title"] = title
    item = _record_decision(store, candidate_id, **updates)
    return {"ok": True, "decision": item}


def find_candidate(store: Any, candidate_id: str, project: str | Path = ".") -> dict[str, Any] | None:
    """Find a candidate by inbox id."""
    candidates = memory_inbox(store, project, limit=200).get("candidates", [])
    return next((item for item in candidates if item.get("id") == candidate_id), None)


def _record_decision(store: Any, candidate_id: str, **updates: Any) -> dict[str, Any]:
    items = store.read(DECISION_STORE, [])
    existing = next((item for item in items if item.get("id") == candidate_id), None)
    if existing:
        existing.update(updates)
        existing["updated_at"] = now_iso()
    else:
        existing = {"id": candidate_id, "created_at": now_iso(), **updates}
        items.append(existing)
    store.write(DECISION_STORE, items)
    return existing


def _decisions_by_id(store: Any) -> dict[str, dict[str, Any]]:
    return {item.get("id", ""): item for item in store.read(DECISION_STORE, [])}


def _merge_decision(candidate: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    merged = dict(candidate)
    if decision.get("title"):
        merged["title"] = decision["title"]
    if decision.get("body"):
        merged["body"] = decision["body"]
    merged["status"] = decision.get("status", "pending")
    return merged


def _session_candidates(limit: int = 5) -> list[dict[str, Any]]:
    candidates = []
    for event in session_timeline()[:limit]:
        detail = {k: v for k, v in event.items() if k not in {"ts", "event"}}
        if not detail:
            continue
        event_id = event.get("session") or event.get("id") or event.get("ts", "")
        title = f"Session event: {event.get('event', 'event')}"
        candidates.append(
            {
                "id": f"promoted_session_{_slug(str(event_id) + '_' + title)}",
                "type": "pattern",
                "source": "session",
                "source_id": str(event_id),
                "title": title,
                "body": f"# {title}\n\nTimestamp: {event.get('ts', '')}\n\nDetails: {detail}\n",
                "tags": ["session"],
                "links": [],
            }
        )
    return candidates


def _slug(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60] or "item"
