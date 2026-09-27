"""S-2: the CLI contract must not change by accident.

tests/golden/cli_contract.json snapshots every command's structure (names,
help, parameters, defaults, hidden flags, help panels, subcommand order) and the
JSON shape of the offline machine-facing commands. Refactors such as the
cli/main.py split must leave both identical. After an intended CLI change,
regenerate with `python tests/golden/generate_cli_contract.py` and review the
diff.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from magent.cli import main as cli_main
from tests.unit.cli_contract import JSON_CASES, command_tree, run_json_case

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "cli_contract.json"
EXPECTED = json.loads(GOLDEN.read_text(encoding="utf-8"))
REGENERATE = "python tests/golden/generate_cli_contract.py"


def _diff_paths(expected, actual, path="") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                out.append(f"{path}/{key}: removed")
            elif key not in expected:
                out.append(f"{path}/{key}: added")
            else:
                out.extend(_diff_paths(expected[key], actual[key], f"{path}/{key}"))
        return out
    if isinstance(expected, list) and isinstance(actual, list) and path.startswith("/shape"):
        # An empty list carries no element shape (it depends on local state,
        # such as which optional tools are installed), so it matches any list.
        if not expected or not actual:
            return []
    return [] if expected == actual else [f"{path}: {expected!r} -> {actual!r}"]


def test_command_tree_matches_the_golden_contract() -> None:
    differences = _diff_paths(EXPECTED["commands"], command_tree(cli_main.app))
    assert not differences, (
        "CLI contract changed; if intended, run " + REGENERATE + ":\n" + "\n".join(differences[:40])
    )


@pytest.mark.parametrize("case", JSON_CASES, ids=[" ".join(case) for case in JSON_CASES])
def test_json_shapes_match_the_golden_contract(case, tmp_path: Path) -> None:
    from tests.unit.test_cli import redirect_config

    mp = pytest.MonkeyPatch()
    try:
        redirect_config(mp, tmp_path)
        project = tmp_path / "project"
        project.mkdir()
        actual = run_json_case(cli_main.app, case, project)
    finally:
        mp.undo()
    expected = EXPECTED["json_shapes"][" ".join(case)]
    differences = _diff_paths(expected, actual)
    assert not differences, (
        "JSON shape changed; if intended, run " + REGENERATE + ":\n" + "\n".join(differences[:40])
    )
