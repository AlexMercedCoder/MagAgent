"""Regressions for durability, caps, and state-handling defects."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from magent import workbench_store as store_module
from magent.workbench_store import WorkbenchStore, _next_id, _singular


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> WorkbenchStore:
    monkeypatch.setattr(store_module, "USERS_DIR", tmp_path / "users")
    return WorkbenchStore("durability")


class TestWorkbenchStoreDurability:
    def test_writes_are_atomic(self, store: WorkbenchStore) -> None:
        """A reader must see the old file or the whole new one, never a
        truncated middle."""
        store.write("tasks", [{"id": "task_0001"}])
        path = store.root / "tasks.json"
        assert json.loads(path.read_text(encoding="utf-8")) == [{"id": "task_0001"}]
        # No temp files left behind.
        assert not list(store.root.glob("*.tmp"))

    def test_corrupt_file_is_preserved_not_silently_replaced(self, store: WorkbenchStore) -> None:
        """read() used to swallow every error and return the default, so the
        next append rewrote the file with one item and lost every task."""
        store.write("tasks", [{"id": "task_0001", "title": "important"}])
        (store.root / "tasks.json").write_text('[{"id": "task_00', encoding="utf-8")

        value = store.read("tasks", [])

        assert value == []
        assert store.warnings, "a corrupt file must be reported"
        quarantined = list(store.root.glob("tasks.json.corrupt-*"))
        assert quarantined, "the unreadable file must be kept, not overwritten"
        assert "task_00" in quarantined[0].read_text(encoding="utf-8")

    def test_append_assigns_sequential_ids(self, store: WorkbenchStore) -> None:
        first = store.append("tasks", {"title": "one"})
        second = store.append("tasks", {"title": "two"})
        assert first["id"] == "task_0001"
        assert second["id"] == "task_0002"
        assert len(store.read("tasks", [])) == 2

    def test_mutate_runs_under_a_lock(self, store: WorkbenchStore) -> None:
        def change(data: list) -> tuple[list, int]:
            data.append({"id": "x"})
            return data, len(data)

        assert store.mutate("things", [], change) == 1
        assert store.mutate("things", [], change) == 2

    def test_singular_uses_removesuffix(self) -> None:
        """`rstrip("s")` ate every trailing s: "progress" became "progre"."""
        assert _singular("tasks") == "task"
        assert _singular("progress") == "progres"  # removesuffix drops exactly one
        assert _next_id([], _singular("tasks")) == "task_0001"

    @pytest.mark.skipif(os.name != "posix", reason="advisory locks are POSIX here")
    def test_lock_is_released(self, store: WorkbenchStore) -> None:
        with store.lock("tasks"):
            pass
        with store.lock("tasks"):  # would block forever if never released
            pass


class TestSubAgentCap:
    @pytest.mark.asyncio
    async def test_cap_counts_running_not_lifetime_spawns(self, tmp_path: Path) -> None:
        """The cap is on concurrency. Counting finished tasks made `/spawn`
        fail forever after N total spawns, and broke step 4 of every
        orchestrated goal."""
        from types import SimpleNamespace

        from magent.subagents import SubAgentRunner, SubAgentTask

        runner = SubAgentRunner(
            username="test",
            provider=None,
            extraction_provider=None,
            cwd=str(tmp_path),
            config=SimpleNamespace(max_subagents=2, max_parallel_subagents=2),
            quiet=True,
        )

        # Two finished tasks must not consume the cap.
        for index in range(2):
            done = SubAgentTask(task_id=f"old{index}", description="finished")
            done.done = True
            runner._tasks[done.task_id] = done

        assert sum(1 for task in runner._tasks.values() if not task.done) == 0

        # With two *finished* tasks recorded, a new spawn must still be allowed.
        spawned = await runner.spawn("fresh", "do a thing")
        assert "Sub-agent cap reached" not in (spawned.error or "")


class TestRecipeOverride:
    def test_saved_recipe_shadows_builtin(self, tmp_path: Path, monkeypatch) -> None:
        """save_recipe stored and listed the override, but run_recipe always
        picked the built-in."""
        from magent.recipes import BUILTIN_RECIPES, get_recipe

        builtin_name = next(iter(BUILTIN_RECIPES))

        class FakeStore:
            def read(self, name, default):
                return [{"name": builtin_name, "description": "mine", "steps": ["custom"]}]

        resolved = get_recipe(FakeStore(), builtin_name, project=tmp_path)
        assert resolved["description"] == "mine"


class TestProviderReadiness:
    def test_keyring_credentials_count_as_configured(self) -> None:
        """After `magent auth add`, doctor/readiness reported "not ready"
        because only env and inline keys were checked."""
        from magent.config_ux import provider_readiness

        result = provider_readiness("anthropic", {"api_key_keyring": "provider:anthropic"})

        assert result["credential_configured"] is True
        assert result["ready"] is True
        assert result["keyring"] is True


class TestDbReadOnlyQuery:
    def test_cte_write_is_denied(self, tmp_path: Path, monkeypatch) -> None:
        """`WITH x AS (SELECT 1) DELETE FROM t` passed the SELECT/WITH prefix
        check and executed."""
        import magent.tools.db as db_module

        monkeypatch.setattr(db_module, "USERS_DIR", tmp_path)
        db_module.close_database_connections()

        db_module.db_execute("dbuser", "CREATE TABLE t (a INTEGER)")
        db_module.db_execute("dbuser", "INSERT INTO t VALUES (1)")

        denied = db_module.db_query("dbuser", "WITH x AS (SELECT 1) DELETE FROM t")
        assert denied["ok"] is False

        remaining = db_module.db_query("dbuser", "SELECT * FROM t")
        assert remaining["count"] == 1
        db_module.close_database_connections()

    def test_attach_and_vacuum_into_are_refused(self, tmp_path: Path, monkeypatch) -> None:
        import magent.tools.db as db_module

        monkeypatch.setattr(db_module, "USERS_DIR", tmp_path)
        db_module.close_database_connections()

        assert db_module.db_execute("dbuser", "ATTACH DATABASE '/tmp/x.db' AS x")["ok"] is False
        assert db_module.db_execute("dbuser", "VACUUM INTO '/tmp/leak.db'")["ok"] is False
        db_module.close_database_connections()
