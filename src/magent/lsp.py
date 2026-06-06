"""LSP-adjacent code intelligence with graceful local fallbacks."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Any

from magent.project_scan import iter_project_files

LSP_COMMANDS = {
    "python": ["pylsp", "pyright-langserver"],
    "typescript": ["typescript-language-server"],
    "rust": ["rust-analyzer"],
    "go": ["gopls"],
}


def lsp_status() -> dict[str, Any]:
    return {
        "ok": True,
        "servers": [
            {"language": language, "command": command, "available": shutil.which(command) or ""}
            for language, commands in LSP_COMMANDS.items()
            for command in commands
        ],
    }


def lsp_symbols(root: str | Path = ".", query: str = "") -> dict[str, Any]:
    root_path = Path(root).resolve()
    symbols = []
    q = query.lower()
    for path in iter_project_files(root_path, suffixes={".py"}, limit=1500):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        rel = path.relative_to(root_path).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                item = {"name": node.name, "kind": kind, "path": rel, "line": node.lineno}
                if not q or q in node.name.lower() or q in rel.lower():
                    symbols.append(item)
    return {"ok": True, "root": str(root_path), "symbols": symbols[:500], "source": "ast-fallback"}


def lsp_diagnostics(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    diagnostics = []
    for path in iter_project_files(root_path, suffixes={".py"}, limit=1500):
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except SyntaxError as e:
            diagnostics.append(
                {
                    "path": path.relative_to(root_path).as_posix(),
                    "line": e.lineno or 0,
                    "column": e.offset or 0,
                    "severity": "error",
                    "message": e.msg,
                }
            )
        except Exception as e:
            diagnostics.append(
                {
                    "path": path.relative_to(root_path).as_posix(),
                    "line": 0,
                    "column": 0,
                    "severity": "warning",
                    "message": str(e),
                }
            )
    return {"ok": not diagnostics, "root": str(root_path), "diagnostics": diagnostics, "source": "ast-fallback"}


def lsp_definition(root: str | Path, symbol: str) -> dict[str, Any]:
    matches = [item for item in lsp_symbols(root, symbol)["symbols"] if item["name"] == symbol]
    return {"ok": bool(matches), "symbol": symbol, "definitions": matches[:20], "source": "ast-fallback"}


def lsp_references(root: str | Path, symbol: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    refs = []
    for path in iter_project_files(root_path, suffixes={".py", ".js", ".ts", ".tsx", ".jsx"}, limit=2000):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines, start=1):
            if symbol in line:
                refs.append(
                    {
                        "path": path.relative_to(root_path).as_posix(),
                        "line": index,
                        "text": line.strip()[:240],
                    }
                )
    return {"ok": True, "symbol": symbol, "references": refs[:200], "source": "text-fallback"}
