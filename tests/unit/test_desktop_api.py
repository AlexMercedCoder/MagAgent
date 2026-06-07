from __future__ import annotations

from pathlib import Path

from magent import config as magent_config
from magent import desktop_api
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
    db_tools._connection_cache.clear()


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
