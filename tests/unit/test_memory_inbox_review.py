from __future__ import annotations

from pathlib import Path

from magent import memory_inbox
from magent.workbench_store import WorkbenchStore


class FakeMemory:
    def __init__(self) -> None:
        self.writes = 0

    def assess_candidate(self, item):
        return {
            "ok": False,
            "duplicates": ["existing"],
            "conflicts": [],
            "requires_review": True,
        }

    def write_memories(self, items, project_slug=None):
        self.writes += len(items)
        return len(items)

    def changed_since(self, since):
        return []


def test_inbox_requires_review_before_promoting_duplicate(tmp_path: Path, monkeypatch) -> None:
    store = WorkbenchStore.__new__(WorkbenchStore)
    store.username = "alice"
    store.root = tmp_path / "workbench"
    store.root.mkdir()
    candidate = {
        "id": "candidate_1",
        "type": "fact",
        "source": "task",
        "source_id": "task_1",
        "title": "Existing fact",
        "body": "Use durable tasks.",
        "tags": [],
        "links": [],
    }
    monkeypatch.setattr(memory_inbox, "promotion_candidates", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(memory_inbox, "_session_candidates", lambda limit=5: [])
    memory = FakeMemory()

    blocked = memory_inbox.accept_candidate(store, memory, "candidate_1", tmp_path)
    accepted = memory_inbox.accept_candidate(
        store, memory, "candidate_1", tmp_path, force=True
    )

    assert blocked["review_required"] is True
    assert memory.writes == 1
    assert accepted["ok"] is True
