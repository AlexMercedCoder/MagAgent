"""SQLite structured data cache tools for MagAgent.

Per-user databases stored at:
  ~/.config/magent/users/<name>/databases/<db_name>.db

The agent can create named databases ("default", "myproject", "analytics", etc.)
or databases are auto-named by project slug when working inside a project.

WAL mode is always enabled for performance and concurrent reads.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from pathlib import Path
from typing import Any

from magent.config import USERS_DIR

# Per-connection cache (username+db_name → connection)
_connection_cache: dict[str, sqlite3.Connection] = {}


def _db_path(username: str, db_name: str = "default") -> Path:
    """Resolve the database file path for a user + database name."""
    # Sanitise name: alphanumeric, hyphens, underscores only
    safe_name = "".join(c for c in db_name if c.isalnum() or c in "-_").strip("_-") or "default"
    db_dir = USERS_DIR / username / "databases"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / f"{safe_name}.db"


def _get_db(username: str, db_name: str = "default") -> sqlite3.Connection:
    """Open (or return cached) WAL-mode SQLite connection."""
    cache_key = f"{username}::{db_name}"
    if cache_key in _connection_cache:
        return _connection_cache[cache_key]

    path = _db_path(username, db_name)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        PRAGMA temp_store = MEMORY;
        PRAGMA cache_size = -32000;
        PRAGMA foreign_keys = ON;
    """)

    # Bootstrap metadata table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO _meta VALUES ('created_at', ?)",
        (str(int(time.time())),),
    )
    conn.execute(
        "INSERT OR IGNORE INTO _meta VALUES ('db_name', ?)",
        (db_name,),
    )
    conn.commit()

    _connection_cache[cache_key] = conn
    return conn


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def list_databases(username: str) -> dict[str, Any]:
    """List all databases for a user."""
    db_dir = USERS_DIR / username / "databases"
    if not db_dir.exists():
        return {"ok": True, "databases": []}

    dbs = []
    for f in sorted(db_dir.glob("*.db")):
        dbs.append(
            {
                "name": f.stem,
                "path": str(f),
                "size_bytes": f.stat().st_size,
            }
        )
    return {"ok": True, "databases": dbs}


def db_query(
    username: str, sql: str, params: list | None = None, db_name: str = "default"
) -> dict[str, Any]:
    """
    Execute a SELECT query and return rows as JSON.
    Use db_name to target a specific named database (default: "default").
    Only SELECT statements are allowed — use db_execute for writes.
    """
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT") and not sql_stripped.startswith("WITH"):
        return {
            "ok": False,
            "error": "db_query only supports SELECT/WITH. Use db_execute for writes.",
        }

    try:
        conn = _get_db(username, db_name)
        cursor = conn.execute(sql, params or [])
        rows = _rows_to_dicts(cursor.fetchall())
        cols = [d[0] for d in cursor.description] if cursor.description else []
        return {
            "ok": True,
            "db": db_name,
            "columns": cols,
            "rows": rows,
            "count": len(rows),
        }
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e), "db": db_name}


def db_execute(
    username: str, sql: str, params: list | None = None, db_name: str = "default"
) -> dict[str, Any]:
    """
    Execute a write statement: INSERT, UPDATE, DELETE, CREATE TABLE, etc.
    Use db_name to target or create a specific named database.
    """
    try:
        conn = _get_db(username, db_name)
        cursor = conn.execute(sql, params or [])
        conn.commit()
        return {
            "ok": True,
            "db": db_name,
            "rows_affected": cursor.rowcount,
            "last_insert_rowid": cursor.lastrowid,
        }
    except sqlite3.Error as e:
        with contextlib.suppress(Exception):
            conn.rollback()
        return {"ok": False, "error": str(e), "db": db_name}


def db_list_tables(username: str, db_name: str = "default") -> dict[str, Any]:
    """List all user-created tables in a database with row counts."""
    try:
        conn = _get_db(username, db_name)
        tables_cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB '_*' ORDER BY name"
        )
        tables = [row["name"] for row in tables_cur.fetchall()]

        result = []
        for table in tables:
            try:
                count_cur = conn.execute(f'SELECT COUNT(*) as n FROM "{table}"')  # noqa: S608
                n = count_cur.fetchone()["n"]
            except Exception:
                n = -1
            result.append({"table": table, "rows": n})

        path = _db_path(username, db_name)
        return {
            "ok": True,
            "db": db_name,
            "path": str(path),
            "tables": result,
            "table_count": len(result),
            "db_size_bytes": path.stat().st_size if path.exists() else 0,
        }
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e), "db": db_name}


def db_schema(username: str, table: str, db_name: str = "default") -> dict[str, Any]:
    """Show the CREATE TABLE statement and column info for a table."""
    try:
        conn = _get_db(username, db_name)
        create_cur = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        row = create_cur.fetchone()
        if not row:
            return {"ok": False, "error": f"Table '{table}' not found in db '{db_name}'"}

        pragma_cur = conn.execute(f'PRAGMA table_info("{table}")')
        columns = [
            {
                "name": r["name"],
                "type": r["type"],
                "not_null": bool(r["notnull"]),
                "default": r["dflt_value"],
                "primary_key": bool(r["pk"]),
            }
            for r in pragma_cur.fetchall()
        ]

        return {
            "ok": True,
            "db": db_name,
            "table": table,
            "create_sql": row["sql"],
            "columns": columns,
        }
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e), "db": db_name}
