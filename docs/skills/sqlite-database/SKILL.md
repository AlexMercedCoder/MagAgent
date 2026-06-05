---
name: sqlite-database
description: Design, create, and manage SQLite databases using MagAgent's built-in db tools. Supports named databases per user, per project, or user-specified.
version: "1.0"
trigger_keywords:
  - sqlite
  - database
  - sql
  - table
  - insert
  - select
  - query
  - schema
  - db
  - relational
tools_required:
  - db_query
  - db_execute
  - db_list_tables
  - db_schema
  - db_list_databases
---

# SQLite Database Usage

MagAgent has built-in SQLite support. Each user can have multiple named databases:

- `"default"` — general-purpose catch-all
- `"<project-name>"` — data specific to a project (e.g., `"maagent"`)  
- `"analytics"`, `"contacts"`, `"tasks"` — purpose-specific databases
- Any name you specify — just pass `db_name="your_name"`

All databases are stored at: `~/.config/magent/users/<username>/databases/<name>.db`

## See What Databases Exist

```
db_list_databases()
```

## Create a Table

```
db_execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        project TEXT,
        status TEXT DEFAULT 'todo',
        priority INTEGER DEFAULT 3,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        due_date DATE,
        notes TEXT
    )
""", db_name="tasks")
```

## Insert Data

```
# Single row
db_execute(
    "INSERT INTO tasks (title, project, priority, due_date) VALUES (?, ?, ?, ?)",
    params=["Write API docs", "backend", 2, "2026-06-10"],
    db_name="tasks"
)

# Multiple rows (use run_python for loops)
```

```python
import sqlite3
from pathlib import Path

conn = sqlite3.connect(str(Path.home() / ".config/magent/users/alex/databases/tasks.db"))
rows = [
    ("Set up CI/CD", "devops", 1, "2026-06-08"),
    ("Code review PR #42", "backend", 2, "2026-06-07"),
]
conn.executemany(
    "INSERT INTO tasks (title, project, priority, due_date) VALUES (?, ?, ?, ?)",
    rows
)
conn.commit()
```

## Query Data

```
# All open tasks, high priority first
db_query(
    "SELECT id, title, project, status, due_date FROM tasks WHERE status != 'done' ORDER BY priority ASC, due_date ASC",
    db_name="tasks"
)

# Filter by project
db_query(
    "SELECT * FROM tasks WHERE project = ? AND status = 'todo'",
    params=["backend"],
    db_name="tasks"
)

# Aggregate
db_query(
    "SELECT project, COUNT(*) as count, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done FROM tasks GROUP BY project",
    db_name="tasks"
)
```

## Update and Delete

```
# Mark task done
db_execute(
    "UPDATE tasks SET status = 'done' WHERE id = ?",
    params=[5],
    db_name="tasks"
)

# Delete old completed tasks
db_execute(
    "DELETE FROM tasks WHERE status = 'done' AND created_at < date('now', '-30 days')",
    db_name="tasks"
)
```

## Inspect Schema

```
# List all tables with row counts
db_list_tables(db_name="tasks")

# See column definitions for a table
db_schema("tasks", db_name="tasks")
```

## Per-Project Database Pattern

When working inside a project, use the project name as `db_name`:

```
# Working on "ecommerce" project
db_execute("CREATE TABLE IF NOT EXISTS products (...)", db_name="ecommerce")
db_execute("CREATE TABLE IF NOT EXISTS orders (...)", db_name="ecommerce")
db_query("SELECT * FROM products WHERE stock < 10", db_name="ecommerce")
```

## Common Schemas

### Tasks / Todo
```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    project TEXT,
    status TEXT DEFAULT 'todo',   -- todo, in_progress, done, blocked
    priority INTEGER DEFAULT 3,   -- 1=high, 5=low
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    due_date DATE,
    tags TEXT,                     -- comma-separated
    notes TEXT
);
```

### Contacts / People
```sql
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    company TEXT,
    role TEXT,
    phone TEXT,
    notes TEXT,
    tags TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Web Research Cache
```sql
CREATE TABLE research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    url TEXT,
    title TEXT,
    content TEXT,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    project TEXT
);
CREATE INDEX idx_research_query ON research(query);
```

### Key-Value Store
```sql
CREATE TABLE kv (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```
