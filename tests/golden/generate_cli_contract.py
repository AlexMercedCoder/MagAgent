"""Regenerate tests/golden/cli_contract.json (S-2 CLI contract snapshot).

Run from the repository root: `python tests/golden/generate_cli_contract.py`.
Only regenerate on purpose, after reviewing that a CLI change is intended.
It uses a throwaway HOME, so it never reads or writes your real MagAgent state.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME = Path(tempfile.mkdtemp(prefix="magent-contract-home-"))
os.environ["HOME"] = str(HOME)
os.environ["NO_COLOR"] = "1"
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from tests.unit.cli_contract import JSON_CASES, command_tree, run_json_case  # noqa: E402


def main() -> None:
    from magent.cli.main import app

    project = HOME / "project"
    project.mkdir()
    shapes = {}
    for case in JSON_CASES:
        shapes[" ".join(case)] = run_json_case(app, case, project)
    document = {"commands": command_tree(app), "json_shapes": shapes}
    target = ROOT / "tests" / "golden" / "cli_contract.json"
    target.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(shapes)} JSON shapes)")


if __name__ == "__main__":
    main()
