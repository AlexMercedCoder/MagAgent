from __future__ import annotations

from pathlib import Path

from magent import config as magent_config
from magent import desktop_api
from magent.task_runtime import TaskRuntime
from magent.tools import db as db_tools


def redirect_config(monkeypatch, root: Path) -> None:
    cfg_dir = root / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", cfg_dir / "users" / "current")
    monkeypatch.setattr(desktop_api, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(desktop_api, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(desktop_api, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(db_tools, "USERS_DIR", cfg_dir / "users")
    db_tools.close_database_connections()


def test_system_info_and_config_get_set_are_redacted(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")

    set_result = desktop_api.config_set("providers.openai.api_key", "sk-secret", scope="global")
    config = desktop_api.config_get("alice")
    info = desktop_api.system_info()

    assert set_result["ok"] is True
    assert info["magent_version"]
    assert config["global"]["providers"]["openai"]["api_key"] == "***"


def test_config_schema_reports_guided_fields(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")
    desktop_api.config_set("defaults.provider", "openai", scope="global")

    schema = desktop_api.config_schema("alice")

    provider = next(item for item in schema["fields"] if item["path"] == "defaults.provider")
    assert schema["ok"] is True
    assert provider["value"] == "openai"
    assert provider["category"] == "provider"
    assert any(item["path"] == "session_messaging.policy" for item in schema["fields"])


def test_sqlite_desktop_helpers_list_query_and_schema(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")
    from magent.tools.db import db_execute

    db_execute("alice", "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)", db_name="demo")
    db_execute("alice", "INSERT INTO items (name) VALUES (?)", ["one"], db_name="demo")

    listed = desktop_api.sqlite_list("alice")
    tables = desktop_api.sqlite_tables("alice", "demo")
    schema = desktop_api.sqlite_table_schema("alice", "items", "demo")
    query = desktop_api.sqlite_query("alice", "SELECT name FROM items", "demo")

    assert listed["databases"][0]["name"] == "demo"
    assert tables["tables"][0]["table"] == "items"
    assert schema["columns"][1]["name"] == "name"
    assert query["rows"] == [{"name": "one"}]


def test_memory_update_node_preview_reports_hashes(monkeypatch, tmp_path: Path) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")

    class FakeManager:
        def __init__(self, *args, **kwargs):
            self.body = "old"

        def read_node(self, node_id):
            return {"id": node_id, "body": self.body, "links": []}

        def update_node(self, node_id, *, body=None, links=None):
            self.body = body or self.body
            return {"ok": True, "id": node_id, "links": links or []}

    monkeypatch.setattr(desktop_api, "MemoryManager", FakeManager)

    preview = desktop_api.memory_update_node("alice", "pref", body="new", preview=True)
    updated = desktop_api.memory_update_node("alice", "pref", body="new")

    assert preview["ok"] is True
    assert preview["preview"] is True
    assert preview["before_hash"] != preview["after_hash"]
    assert updated["before_hash"] != updated["after_hash"]


def test_memory_batch_desktop_contract(monkeypatch, tmp_path: Path) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")

    class FakeManager:
        def __init__(self, *args, **kwargs):
            pass

        def apply_batch(self, operations, *, preview=False):
            return {"ok": True, "preview": preview, "operations": operations}

    monkeypatch.setattr(desktop_api, "MemoryManager", FakeManager)
    operations = [{"op": "suppress", "id": "stale", "reason": "old"}]

    result = desktop_api.memory_apply_batch("alice", operations, preview=True)

    assert result == {"ok": True, "preview": True, "operations": operations}


def test_desktop_execution_task_contract(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")
    runtime = TaskRuntime(magent_config.USERS_DIR / "alice" / "workbench")
    task = runtime.create("ask", "Desktop task", project=tmp_path)
    runtime.transition(task["id"], "running")

    listed = desktop_api.execution_tasks("alice")
    detail = desktop_api.execution_task("alice", task["id"])
    cancelled = desktop_api.execution_task_action("alice", task["id"], "cancel")

    assert listed["tasks"][0]["schema_version"] == "magent.task.v1"
    assert detail["events"][0]["type"] == "task_created"
    assert cancelled["task"]["state"] == "cancelled"
