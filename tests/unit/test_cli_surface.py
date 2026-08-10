"""Whole-CLI invariants.

Two bugs shipped because nothing ever walked the command tree:

* `magent run` called `plan_cmd` as a plain function, so every parameter kept
  its truthy `typer.OptionInfo` default and the command crashed with
  "'OptionInfo' object is not iterable" — after appending a runs record.
* `magent config schema` was registered twice; the later registration won and
  the `--user` variant desktop integrations rely on became unreachable.

Both are caught here for every command, not just the two that were reported.
"""

from __future__ import annotations

import typer
from typer.testing import CliRunner

from magent.cli import main as cli_main

runner = CliRunner()


def _walk(app: typer.Typer, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every leaf command path in the app."""
    leaves: list[tuple[str, ...]] = []

    for command in app.registered_commands:
        name = command.name or (command.callback.__name__.replace("_", "-") if command.callback else "")
        if name:
            leaves.append((*prefix, name))

    for group in app.registered_groups:
        if group.typer_instance is None:
            continue
        name = group.name or ""
        leaves.extend(_walk(group.typer_instance, (*prefix, name) if name else prefix))

    return leaves


def _duplicate_names(app: typer.Typer, prefix: str = "") -> list[str]:
    """Names registered more than once in the same group."""
    duplicates: list[str] = []

    seen: set[str] = set()
    for command in app.registered_commands:
        name = command.name or (command.callback.__name__.replace("_", "-") if command.callback else "")
        if name in seen:
            duplicates.append(f"{prefix}{name}")
        seen.add(name)

    for group in app.registered_groups:
        if group.typer_instance is None:
            continue
        if group.name in seen:
            duplicates.append(f"{prefix}{group.name}")
        seen.add(group.name or "")
        duplicates.extend(_duplicate_names(group.typer_instance, f"{prefix}{group.name} "))

    return duplicates


ALL_COMMANDS = _walk(cli_main.app)


def test_command_tree_is_discovered() -> None:
    assert len(ALL_COMMANDS) > 50, "command walker found suspiciously few commands"


def test_no_group_registers_a_duplicate_name() -> None:
    """A duplicate silently shadows the earlier registration (bug #22)."""
    assert _duplicate_names(cli_main.app) == []


def test_every_command_responds_to_help() -> None:
    """`--help` builds the parameter list, so a command whose signature cannot
    be constructed fails here rather than in a user's terminal."""
    failures = []
    for path in ALL_COMMANDS:
        result = runner.invoke(cli_main.app, [*path, "--help"])
        if result.exit_code != 0:
            failures.append(f"{' '.join(path)} → exit {result.exit_code}: {result.output[-300:]}")
    assert not failures, "commands failed --help:\n" + "\n".join(failures)


def test_run_command_does_not_call_a_typer_command_as_a_function(tmp_path, monkeypatch) -> None:
    """Regression for bug #18."""
    import magent.workbench_store as workbench_store

    monkeypatch.setattr(workbench_store, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(cli_main, "_store", lambda: workbench_store.WorkbenchStore("smoke"))

    result = runner.invoke(cli_main.app, ["run", "ship the thing", "--project", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "OptionInfo" not in result.output
    assert "Planned run" in result.output


def test_config_schema_keeps_the_user_variant() -> None:
    """Regression for bug #22: the desktop schema takes --user again."""
    result = runner.invoke(cli_main.app, ["config", "schema", "--help"])
    assert result.exit_code == 0
    assert "--user" in result.output
