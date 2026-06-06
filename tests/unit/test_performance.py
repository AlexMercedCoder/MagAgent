from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from magent import config as magent_config
from magent import workbench
from magent.performance import performance_doctor
from magent.project_scan import iter_project_files, scan_estimate
from magent.workbench_maintenance import compact_workbench, prune_workbench, workbench_stats


def redirect_config(monkeypatch, root: Path) -> None:
    cfg_dir = root / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", cfg_dir / "users" / "current")


def test_project_scan_uses_bounds_and_ignores(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("", encoding="utf-8")
    for i in range(3):
        (tmp_path / f"file_{i}.py").write_text("", encoding="utf-8")

    files = list(iter_project_files(tmp_path, suffixes={".py"}, limit=2))
    estimate = scan_estimate(tmp_path, limit=2)

    assert len(files) == 2
    assert all(".venv" not in path.parts for path in files)
    assert estimate["truncated"] is True


def test_workbench_maintenance_stats_prune_and_compact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(workbench, "USERS_DIR", tmp_path / "users")
    store = workbench.WorkbenchStore("alice")
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    recent = datetime.now(UTC).isoformat()
    store.write(
        "events",
        [
            {"id": "event_0001", "created_at": old, "title": "old"},
            {"id": "event_0002", "created_at": recent, "title": "recent"},
        ],
    )

    stats = workbench_stats(store)
    pruned = prune_workbench(store, older_than_days=30, keep=1)
    compacted = compact_workbench(store)

    assert stats["ok"] is True
    assert any(item["store"] == "events" for item in stats["stores"])
    event_change = next(item for item in pruned["changes"] if item["store"] == "events")
    assert event_change["removed"] == 1
    assert compacted["ok"] is True
    assert len(store.read("events", [])) == 1


def test_performance_doctor_reports_local_state(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setattr(workbench, "USERS_DIR", magent_config.USERS_DIR)
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")
    store = workbench.WorkbenchStore("alice")
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    result = performance_doctor(store, "alice", tmp_path / "project")

    assert result["ok"] is True
    assert result["repo"]["files_seen"] == 1
    assert "load_global_config_ms" in result["timings_ms"]
