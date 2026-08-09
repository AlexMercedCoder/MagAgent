"""JSON query and named SQLite database capability tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from magent.permissions import PermissionResult, RiskTier
from magent.tools.types import ToolResult


class DataToolsMixin:
    """Data capability implementation mixed into the public tool executor."""

    cwd: str
    username: str

    def _path_tier(self, op: str, path: str) -> tuple[Path, RiskTier]:
        raise NotImplementedError

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        raise NotImplementedError

    def _check_permission(self, action_description: str, tier: RiskTier) -> PermissionResult:
        raise NotImplementedError

    def _permission_denied(self, perm: PermissionResult) -> ToolResult:
        raise NotImplementedError

    async def json_query(self, path_or_json: str, query: str) -> ToolResult:
        """Run a JMESPath query over a JSON file or JSON string."""
        self._log_tool("json_query", f"{query!r}", RiskTier.SILENT)
        try:
            import jmespath

            candidate = Path(self.cwd) / path_or_json
            if candidate.exists():
                abs_path, tier = self._path_tier("read", path_or_json)
                perm = self._check_permission(f"Read JSON {abs_path}", tier)
                if not perm.approved:
                    return self._permission_denied(perm)
                data = json.loads(abs_path.read_text())
            else:
                data = json.loads(path_or_json)
            return {"ok": True, "result": jmespath.search(query, data)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def db_query(
        self,
        sql: str,
        params: list[Any] | None = None,
        db_name: str = "default",
    ) -> ToolResult:
        """Select from a named user database."""
        self._log_tool("db_query", f"[{db_name}] {sql[:60]}", RiskTier.SILENT)
        from magent.tools.db import db_query

        return db_query(self.username, sql, params, db_name)

    async def db_execute(
        self,
        sql: str,
        params: list[Any] | None = None,
        db_name: str = "default",
    ) -> ToolResult:
        """Execute a write or schema statement in a named user database."""
        tier = RiskTier.AUTO
        self._log_tool("db_execute", f"[{db_name}] {sql[:60]}", tier)
        perm = self._check_permission(f"DB write [{db_name}]: {sql[:60]}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        from magent.tools.db import db_execute

        return db_execute(self.username, sql, params, db_name)

    async def db_list_tables(self, db_name: str = "default") -> ToolResult:
        """List tables and row counts in a named user database."""
        self._log_tool("db_list_tables", db_name, RiskTier.SILENT)
        from magent.tools.db import db_list_tables

        return db_list_tables(self.username, db_name)

    async def db_schema(self, table: str, db_name: str = "default") -> ToolResult:
        """Show columns and types for a table in a named database."""
        self._log_tool("db_schema", f"[{db_name}].{table}", RiskTier.SILENT)
        from magent.tools.db import db_schema

        return db_schema(self.username, table, db_name)

    async def db_list_databases(self) -> ToolResult:
        """List databases created for the current user."""
        self._log_tool("db_list_databases", self.username, RiskTier.SILENT)
        from magent.tools.db import list_databases

        return list_databases(self.username)
