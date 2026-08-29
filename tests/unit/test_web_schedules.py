from __future__ import annotations

import pytest

from magent.web_schedules import ScheduleStore


class MemoryStore:
    def __init__(self) -> None:
        self.data = {}

    def read(self, name, default):
        return self.data.get(name, default)

    def mutate(self, name, default, change):
        current = self.data.get(name, default)
        updated, result = change(current)
        self.data[name] = updated
        return result


class Graphs:
    def __init__(self) -> None:
        self.started = []

    def preview(self, path):
        if not path.endswith(".agraph.yaml"):
            raise ValueError("invalid graph")
        return {"ok": True}

    def start(self, path, **kwargs):
        self.started.append((path, kwargs))
        return {"job_id": "job_1"}


def test_schedule_lifecycle_and_due_tick() -> None:
    graphs = Graphs()
    schedules = ScheduleStore(MemoryStore(), graphs, "/workspace")
    created = schedules.create("review.agraph.yaml", 15)["schedule"]
    assert schedules.list()["schedules"][0]["status"] == "active"

    schedules.action(created["id"], "pause")
    assert schedules.list()["schedules"][0]["status"] == "paused"
    schedules.action(created["id"], "resume")
    schedules.action(created["id"], "run")
    assert graphs.started[0][0] == "review.agraph.yaml"
    assert schedules.list()["schedules"][0]["last_job_id"] == "job_1"

    schedules.action(created["id"], "delete")
    assert schedules.list()["schedules"] == []


def test_schedule_rejects_invalid_intervals_and_graphs() -> None:
    schedules = ScheduleStore(MemoryStore(), Graphs(), "/workspace")
    with pytest.raises(ValueError, match="interval"):
        schedules.create("review.agraph.yaml", 0)
    with pytest.raises(ValueError, match="invalid graph"):
        schedules.create("review.txt", 10)


def test_schedules_are_scoped_to_the_server_project() -> None:
    store = MemoryStore()
    first = ScheduleStore(store, Graphs(), "/workspace/one")
    second_graphs = Graphs()
    second = ScheduleStore(store, second_graphs, "/workspace/two")
    created = first.create("review.agraph.yaml", 10)["schedule"]

    assert second.list()["schedules"] == []
    assert second.action(created["id"], "pause")["ok"] is False
    second.tick()
    assert second_graphs.started == []
