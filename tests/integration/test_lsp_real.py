from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from magent.lsp import lsp_definition, lsp_diagnostics, lsp_hover


@pytest.mark.skipif(not shutil.which("pylsp"), reason="python-lsp-server is not installed")
def test_python_language_server_round_trip(tmp_path: Path) -> None:
    (tmp_path / "demo.py").write_text("def answer() -> int:\n    return 'bad'\n", encoding="utf-8")
    diagnostics = lsp_diagnostics(tmp_path)
    definition = lsp_definition(tmp_path, "answer")
    hover = lsp_hover(tmp_path, "demo.py", 1, 5)
    assert diagnostics["source"] == "lsp"
    assert definition["source"] == "lsp"
    assert hover["source"] == "lsp"


@pytest.mark.skipif(
    not shutil.which("typescript-language-server"),
    reason="typescript-language-server is not installed",
)
def test_typescript_language_server_round_trip(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions":{"strict":true},"include":["*.ts"]}', encoding="utf-8"
    )
    (tmp_path / "demo.ts").write_text(
        "export function answer(): number { return 42; }\nanswer();\n", encoding="utf-8"
    )
    diagnostics = lsp_diagnostics(tmp_path)
    definition = lsp_definition(tmp_path, "answer")
    hover = lsp_hover(tmp_path, "demo.ts", 1, 17)
    assert diagnostics["source"] == "lsp"
    assert definition["source"] == "lsp"
    assert hover["source"] == "lsp"
