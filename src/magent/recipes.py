"""Reusable workflow recipes for common MagAgent routines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magent.playbook import playbook_commands, playbook_summary
from magent.workbench_store import now_iso

BUILTIN_RECIPES: dict[str, dict[str, Any]] = {
    "release-prep": {
        "name": "release-prep",
        "description": "Prepare a Python project release with checks, docs, and artifacts.",
        "steps": [
            "Inspect workspace status and release readiness.",
            "Run configured test, lint, and build commands.",
            "Update docs, changelog, and version references.",
            "Build distribution artifacts and verify package metadata.",
        ],
        "commands": ["magent release check", "magent docs doctor", "python -m build"],
    },
    "bug-triage": {
        "name": "bug-triage",
        "description": "Turn a bug report into a focused diagnosis and repair plan.",
        "steps": [
            "Capture the failing behavior and reproduction notes.",
            "Inspect related code, tests, and recent command failures.",
            "Draft a narrow fix plan with the smallest relevant checks.",
        ],
        "commands": ["magent context map", "magent test map"],
    },
    "docs-audit": {
        "name": "docs-audit",
        "description": "Check built-in and project docs for command and feature drift.",
        "steps": [
            "Run the built-in docs doctor.",
            "Search docs for recently changed command and feature names.",
            "Update missing reference, architecture, and workflow pages.",
        ],
        "commands": ["magent docs doctor", "magent docs list"],
    },
    "dependency-upgrade": {
        "name": "dependency-upgrade",
        "description": "Upgrade dependencies with test-aware checkpoints.",
        "steps": [
            "Record current dependency and lockfile state.",
            "Upgrade a small dependency set.",
            "Run focused tests, lint, and import checks.",
            "Save any failure patterns to the memory inbox.",
        ],
        "commands": ["magent project doctor", "magent release check"],
    },
    "test-repair": {
        "name": "test-repair",
        "description": "Diagnose failing tests and convert the fix into durable project knowledge.",
        "steps": [
            "Run or inspect the failing test command.",
            "Map related source and test files.",
            "Patch the narrowest behavior and rerun focused checks.",
            "Promote repeated failure patterns into memory.",
        ],
        "commands": ["magent test related", "magent memory inbox"],
    },
    "verify-and-review": {
        "name": "verify-and-review",
        "description": "Run the standard goal-loop verifier and reviewer pass.",
        "steps": [
            "Run project doctor and configured checks.",
            "Verify build/test/lint status and inspect UI output when relevant.",
            "Review the diff with fresh context for critical and medium issues.",
            "Return actionable feedback or mark the contribution ready for human review.",
        ],
        "commands": ["magent project doctor", "magent release check", "magent review --save"],
    },
    "context-hygiene": {
        "name": "context-hygiene",
        "description": "Audit active context, stale plans, memory candidates, and unused project routines.",
        "steps": [
            "Inspect the current context map and memory recall.",
            "Discard or promote stale plans, command failures, and memory candidates.",
            "Trim unused MCP/skills/tool packs before starting a large task.",
        ],
        "commands": ["magent context audit", "magent memory inbox", "magent tools list"],
    },
}


def list_recipes(store: Any, project: str | Path = ".") -> list[dict[str, Any]]:
    """Return built-in and saved workflow recipes."""
    saved = store.read("recipes", [])
    recipes = [*BUILTIN_RECIPES.values(), *saved]
    playbook = playbook_summary(project)
    if playbook.get("commands"):
        recipes.append(
            {
                "name": "project-playbook",
                "description": "Commands and routines from .magent/playbook.toml.",
                "steps": [
                    "Review project-specific command routines.",
                    "Run the commands that match the current task.",
                    "Apply review and context defaults from the playbook.",
                ],
                "commands": playbook_commands(project),
                "source": "playbook",
            }
        )
    return recipes


def get_recipe(store: Any, name: str, project: str | Path = ".") -> dict[str, Any] | None:
    """Find a recipe by name."""
    normalized = _normalize_name(name)
    return next((item for item in list_recipes(store, project) if _normalize_name(item.get("name", "")) == normalized), None)


def save_recipe(
    store: Any,
    name: str,
    *,
    description: str = "",
    steps: list[str] | None = None,
    commands: list[str] | None = None,
) -> dict[str, Any]:
    """Save or replace a user-defined recipe."""
    recipe = {
        "name": _normalize_name(name),
        "description": description,
        "steps": [item for item in steps or [] if item.strip()],
        "commands": [item for item in commands or [] if item.strip()],
        "source": "user",
        "updated_at": now_iso(),
    }
    recipes = [item for item in store.read("recipes", []) if _normalize_name(item.get("name", "")) != recipe["name"]]
    recipes.append(recipe)
    store.write("recipes", sorted(recipes, key=lambda item: item.get("name", "")))
    return recipe


def run_recipe(store: Any, name: str, project: str | Path = ".") -> dict[str, Any]:
    """Materialize a recipe as a pending execution plan."""
    recipe = get_recipe(store, name, project)
    if not recipe:
        return {"ok": False, "error": f"Recipe not found: {name}"}
    from magent.workbench_domains.plans import save_execution_plan

    root = Path(project).resolve()
    goal = f"Run recipe: {recipe['name']}"
    plan = save_execution_plan(store, root, goal, commands=recipe.get("commands", []), include_diff=False)
    updated = store.update_item(
        "plans",
        plan["id"],
        recipe=recipe,
        steps=recipe.get("steps", []),
        status="pending",
    )
    return {"ok": True, "recipe": recipe, "plan": updated or plan}


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")
