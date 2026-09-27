"""The mypy ignore list is a backlog that may only shrink."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Remove a module here in the same change that removes it from pyproject.toml.
ALLOWED_BACKLOG = {
    "magent.agent_defs",
    "magent.agraph.criteria",
    "magent.agraph.mappings",
    "magent.agraph.plan",
    "magent.cli.command_context",
    "magent.cli.commands.graph",
    "magent.cli.commands.permissions",
    "magent.cli.commands.plugins",
    "magent.config",
    "magent.gateway.adapters.slack",
    "magent.goal_orchestrator",
    "magent.model_capabilities",
    "magent.prompt_input",
    "magent.session_controls",
    "magent.tools.web",
    "magent.utils",
}


def test_mypy_ignore_list_never_grows() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignored = {
        module
        for override in config["tool"]["mypy"].get("overrides", [])
        if override.get("ignore_errors")
        for module in override["module"]
    }
    assert ignored <= ALLOWED_BACKLOG, f"new modules exempted from mypy: {ignored - ALLOWED_BACKLOG}"
    assert "magent.cli.main" not in ignored and "magent.workbench" not in ignored
