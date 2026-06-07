from __future__ import annotations

from magent.model_health import (
    model_health_report,
    recommend_model_from_health,
    record_model_health,
)


class Store:
    def __init__(self):
        self.data = {}

    def read(self, name, default):
        return self.data.get(name, default)

    def write(self, name, data):
        self.data[name] = data


def test_model_health_records_and_recommends_successful_model() -> None:
    store = Store()

    record_model_health(store, "opencode-go", "deepseek-v4-flash", task_type="tool-use", ok=True)
    record_model_health(store, "opencode-go", "slow-model", task_type="tool-use", ok=False, error="timeout")

    report = model_health_report(store)
    recommendation = recommend_model_from_health(store, provider="opencode-go", task_type="tool-use")

    assert report["ok"] is True
    assert len(report["recent"]) == 2
    assert recommendation["ok"] is True
    assert recommendation["recommendation"]["model"] == "deepseek-v4-flash"
