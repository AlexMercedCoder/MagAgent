"""Helpers for the CLI contract snapshots (S-2).

`command_tree()` describes every command from the Click objects Typer builds, so it does
not depend on terminal width or Rich rendering: names, help, parameters (with
options, types, defaults, required and hidden flags) and help panels.
`json_shape()` reduces a JSON document to its structure: keys and value types,
with lists represented by their first element.
"""

from __future__ import annotations

from typing import Any

import typer


def _plain(value: Any) -> Any:
    """JSON-safe value; Typer's DefaultPlaceholder unwraps to its value."""
    if type(value).__name__ == "DefaultPlaceholder":
        value = getattr(value, "value", None)
    if isinstance(value, str):
        # Defaults derived from the home directory differ per machine.
        from pathlib import Path

        return value.replace(str(Path.home()), "~")
    if isinstance(value, int | float | bool | type(None)):
        return value
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return type(value).__name__


def _param(parameter: Any) -> dict[str, Any]:
    default = _plain(parameter.default) if not callable(parameter.default) else "callable"
    return {
        "name": parameter.name,
        "kind": "option" if type(parameter).__name__.endswith("Option") else "argument",
        "opts": sorted([*parameter.opts, *getattr(parameter, "secondary_opts", [])]),
        "type": getattr(parameter.type, "name", type(parameter.type).__name__),
        "required": bool(parameter.required),
        "multiple": bool(getattr(parameter, "multiple", False)),
        "nargs": parameter.nargs,
        "default": default,
        "hidden": bool(getattr(parameter, "hidden", False)),
        "is_flag": bool(getattr(parameter, "is_flag", False)),
        "help": str(_plain(getattr(parameter, "help", None)) or "").strip(),
    }


def _command(command: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "help": (command.help or "").strip(),
        "short_help": (command.short_help or "").strip(),
        "hidden": bool(command.hidden),
        "panel": _plain(getattr(command, "rich_help_panel", None)),
        "params": [_param(parameter) for parameter in command.params],
    }
    if hasattr(command, "commands"):
        node["commands"] = {name: _command(sub) for name, sub in sorted(command.commands.items())}
        node["order"] = list(command.commands)
    return node


def command_tree(app: typer.Typer) -> dict[str, Any]:
    return _command(typer.main.get_command(app))


def json_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [json_shape(value[0])] if value else []
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if value is None:
        return "null"
    return "string"


# Read-only commands whose --json (or always-JSON) output is a machine contract
# and that run offline against a fresh user. Commands that start servers, call a
# model, or need existing ids are covered by their own tests instead.
JSON_CASES: list[tuple[str, ...]] = [
    ("system", "info"),
    ("system", "compatibility"),
    ("capabilities", "--json"),
    ("cache", "status", "--json"),
    ("checkpoint", "list", "--json"),
    ("checkpoint", "session-list", "--json"),
    ("events", "list", "--json"),
    ("gateway", "status", "--json"),
    ("get-started", "--json"),
    ("jobs", "--json"),
    ("memory", "evidence", "--json"),
    ("memory", "inbox", "--json"),
    ("permission", "status"),
    ("permission", "classify", "git status", "--json"),
    ("permission", "grants", "list", "--json"),
    ("permission", "approvals-recovery", "--json"),
    ("plugin", "list", "--json"),
    ("provider", "conformance", "--json"),
    ("recipe", "list", "--json"),
    ("session", "peers", "--json"),
    ("config", "schema"),
    ("execution", "list", "--limit", "5"),
]


def run_json_case(app: typer.Typer, case: tuple[str, ...], project: Any) -> Any:
    """Run one case against a fresh user and return its JSON shape (or an error marker)."""
    import json
    import os

    from typer.testing import CliRunner

    runner = CliRunner()
    runner.invoke(app, ["user", "create", "contract"])
    previous = os.getcwd()
    os.chdir(project)
    try:
        result = runner.invoke(app, list(case))
    finally:
        os.chdir(previous)
    text = result.output
    start = min((index for index in (text.find("{"), text.find("[")) if index >= 0), default=-1)
    if start < 0:
        return {"exit_code": result.exit_code, "error": "no JSON output"}
    try:
        payload, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return {"exit_code": result.exit_code, "error": "unparseable JSON"}
    return {"exit_code": result.exit_code, "shape": json_shape(payload)}
