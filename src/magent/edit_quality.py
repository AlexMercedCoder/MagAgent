"""Offline diff-edit quality benchmark (G-10).

Runs the real ``edit_file`` tool over a fixed set of edits, in throwaway
directories, and checks the exact bytes left on disk. It measures whether an
edit lands exactly where intended and nothing else changes: line endings,
trailing newlines, encodings, ambiguous and missing matches, whitespace.

No model is involved, so the score is deterministic and cheap to run in CI:
``magent eval edit-quality [--json]``.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "magent.edit-quality.v1"


@dataclass(frozen=True)
class EditCase:
    id: str
    description: str
    before: bytes
    old: str
    new: str
    expect_ok: bool
    after: bytes | None = None  # None: the file must be unchanged


CASES: tuple[EditCase, ...] = (
    EditCase(
        "exact-single-line",
        "Replace one exact line.",
        b"a = 1\nb = 2\n",
        "b = 2",
        "b = 3",
        True,
        b"a = 1\nb = 3\n",
    ),
    EditCase(
        "multi-line-block",
        "Replace a multi-line block with different indentation.",
        b"def f():\n    x = 1\n    return x\n",
        "    x = 1\n    return x",
        "    return 2",
        True,
        b"def f():\n    return 2\n",
    ),
    EditCase(
        "insert-after-anchor",
        "Insert a line after an anchor.",
        b"import os\n\nprint(os.getcwd())\n",
        "import os\n",
        "import os\nimport sys\n",
        True,
        b"import os\nimport sys\n\nprint(os.getcwd())\n",
    ),
    EditCase(
        "delete-block",
        "Delete a block by replacing it with nothing.",
        b"keep\n# TODO remove\nkeep too\n",
        "# TODO remove\n",
        "",
        True,
        b"keep\nkeep too\n",
    ),
    EditCase(
        "ambiguous-refused",
        "Two identical matches: refuse rather than guess.",
        b"x = 1\ny = 2\nx = 1\n",
        "x = 1",
        "x = 9",
        False,
    ),
    EditCase(
        "missing-refused",
        "No match: refuse and leave the file alone.",
        b"hello\n",
        "goodbye",
        "hi",
        False,
    ),
    EditCase(
        "whitespace-is-significant",
        "A match that differs only in indentation is not the same text.",
        b"if x:\n    run()\n",
        "if x:\n  run()",
        "if x:\n  stop()",
        False,
    ),
    EditCase(
        "crlf-preserved",
        "A CRLF file stays CRLF, including lines the edit did not touch.",
        b"one\r\ntwo\r\nthree\r\n",
        "two",
        "TWO",
        True,
        b"one\r\nTWO\r\nthree\r\n",
    ),
    EditCase(
        "crlf-multiline-match",
        "A multi-line old string written with LF matches a CRLF file and keeps CRLF.",
        b"alpha\r\nbeta\r\ngamma\r\n",
        "alpha\nbeta",
        "alpha\nBETA",
        True,
        b"alpha\r\nBETA\r\ngamma\r\n",
    ),
    EditCase(
        "no-trailing-newline-kept",
        "A file without a final newline does not gain one.",
        b"last line",
        "last",
        "final",
        True,
        b"final line",
    ),
    EditCase(
        "unicode-text",
        "Non-ASCII text round-trips exactly.",
        "caf\u00e9 = '\u2603'\n".encode(),
        "'\u2603'",
        "'\u2744'",
        True,
        "caf\u00e9 = '\u2744'\n".encode(),
    ),
    EditCase(
        "non-utf8-refused",
        "A file that is not UTF-8 is refused instead of being rewritten with replacement characters.",
        b"name = 'Jos\xe9'\nvalue = 1\n",
        "value = 1",
        "value = 2",
        False,
    ),
    EditCase(
        "bom-preserved",
        "A UTF-8 byte-order mark survives the edit.",
        b"\xef\xbb\xbfkey=old\n",
        "key=old",
        "key=new",
        True,
        b"\xef\xbb\xbfkey=new\n",
    ),
)


async def _run_case(case: EditCase, root: Path) -> dict[str, Any]:
    from magent.tools.executor import ToolExecutor

    class BenchmarkExecutor(ToolExecutor):
        # The benchmark must not leave checkpoints in the user's workbench.
        def _checkpoint(self, abs_path: Path, operation: str) -> str:
            return ""

    path = root / "target.txt"
    path.write_bytes(case.before)
    tools = BenchmarkExecutor(
        str(root), permission_mode="yolo", interactive_permissions=False, show_tool_calls=False
    )
    result = await tools.edit_file("target.txt", case.old, case.new)
    after = path.read_bytes()
    expected_after = case.before if case.after is None else case.after
    ok_matches = bool(result.get("ok")) == case.expect_ok
    bytes_match = after == expected_after
    return {
        "id": case.id,
        "description": case.description,
        "passed": ok_matches and bytes_match,
        "expected_ok": case.expect_ok,
        "tool_ok": bool(result.get("ok")),
        "bytes_match": bytes_match,
        "error": str(result.get("error") or ""),
    }


def run_edit_quality() -> dict[str, Any]:
    """Run every case and return a scored report."""

    results = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="magent-edit-") as directory:
            results.append(asyncio.run(_run_case(case, Path(directory))))
    passed = sum(1 for item in results if item["passed"])
    return {
        "ok": passed == len(results),
        "schema": SCHEMA,
        "passed": passed,
        "total": len(results),
        "score": round(passed / len(results), 4) if results else 0.0,
        "cases": results,
    }
