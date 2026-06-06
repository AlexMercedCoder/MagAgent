from __future__ import annotations

import pytest

from magent.tools import ToolExecutor
from magent.tools import db as db_tools


@pytest.fixture(autouse=True)
def isolated_databases(tmp_path, monkeypatch):
    monkeypatch.setattr(db_tools, "USERS_DIR", tmp_path / "users")
    db_tools._connection_cache.clear()
    yield
    for conn in db_tools._connection_cache.values():
        conn.close()
    db_tools._connection_cache.clear()


def test_db_execute_query_schema_and_list_tables() -> None:
    created = db_tools.db_execute(
        "alice",
        "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL)",
        db_name="project",
    )
    inserted = db_tools.db_execute(
        "alice",
        "INSERT INTO notes (body) VALUES (?)",
        ["hello"],
        db_name="project",
    )
    queried = db_tools.db_query("alice", "SELECT body FROM notes", db_name="project")
    schema = db_tools.db_schema("alice", "notes", db_name="project")
    tables = db_tools.db_list_tables("alice", db_name="project")
    databases = db_tools.list_databases("alice")

    assert created["ok"] is True
    assert inserted["last_insert_rowid"] == 1
    assert queried["rows"] == [{"body": "hello"}]
    assert schema["columns"][1]["name"] == "body"
    assert schema["columns"][1]["not_null"] is True
    assert tables["tables"] == [{"table": "notes", "rows": 1}]
    assert databases["databases"][0]["name"] == "project"


def test_db_query_rejects_writes_and_schema_reports_missing_table() -> None:
    rejected = db_tools.db_query("alice", "DELETE FROM notes")
    missing = db_tools.db_schema("alice", "missing")

    assert rejected["ok"] is False
    assert "only supports SELECT" in rejected["error"]
    assert missing["ok"] is False
    assert "not found" in missing["error"]


def test_db_path_sanitizes_database_name(tmp_path) -> None:
    path = db_tools._db_path("alice", "../prod db!")

    assert path.name == "proddb.db"
    assert path.parent == tmp_path / "users" / "alice" / "databases"


@pytest.mark.asyncio
async def test_tool_executor_database_wrappers() -> None:
    tools = ToolExecutor(".", permission_mode="silent", username="alice")

    create = await tools.db_execute("CREATE TABLE items (name TEXT)")
    insert = await tools.db_execute("INSERT INTO items (name) VALUES (?)", ["Ada"])
    rows = await tools.db_query("SELECT name FROM items")
    tables = await tools.db_list_tables()
    schema = await tools.db_schema("items")
    databases = await tools.db_list_databases()

    assert create["ok"] is True
    assert insert["rows_affected"] == 1
    assert rows["rows"] == [{"name": "Ada"}]
    assert tables["table_count"] == 1
    assert schema["columns"][0]["name"] == "name"
    assert databases["databases"][0]["name"] == "default"
