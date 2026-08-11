"""Capability-aware LSP code intelligence with bounded local fallbacks."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from magent.lsp_client import LspClient, LspError, LspServerSpec
from magent.project_scan import iter_project_files

SERVER_SPECS = (
    LspServerSpec("python", ("pyright-langserver", "--stdio"), (".py",)),
    LspServerSpec("python", ("pylsp",), (".py",)),
    LspServerSpec(
        "typescript",
        ("typescript-language-server", "--stdio"),
        (".ts", ".tsx", ".js", ".jsx"),
    ),
    LspServerSpec("rust", ("rust-analyzer",), (".rs",)),
    LspServerSpec("go", ("gopls", "serve"), (".go",)),
)
LSP_COMMANDS = {
    language: [spec.command[0] for spec in SERVER_SPECS if spec.language == language]
    for language in {spec.language for spec in SERVER_SPECS}
}


def lsp_status() -> dict[str, Any]:
    servers = []
    for spec in SERVER_SPECS:
        executable = shutil.which(spec.command[0]) or ""
        servers.append(
            {
                "language": spec.language,
                "command": list(spec.command),
                "available": executable,
                "extensions": list(spec.extensions),
            }
        )
    return {
        "ok": True,
        "servers": servers,
        "real_servers": sum(bool(s["available"]) for s in servers),
    }


def lsp_symbols(root: str | Path = ".", query: str = "") -> dict[str, Any]:
    root_path = Path(root).resolve()
    spec = _first_available_spec(root_path)
    if spec:
        try:
            with _client(spec, root_path) as client:
                if client.supports("workspaceSymbolProvider"):
                    result = client.request("workspace/symbol", {"query": query}) or []
                    symbols = [
                        _symbol(item, root_path) for item in result if isinstance(item, dict)
                    ]
                    return {
                        "ok": True,
                        "root": str(root_path),
                        "symbols": symbols[:500],
                        "source": "lsp",
                        "server": spec.command[0],
                    }
        except LspError as exc:
            return _fallback_symbols(root_path, query, str(exc))
    return _fallback_symbols(root_path, query, "no compatible language server installed")


def lsp_diagnostics(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    files = list(
        iter_project_files(
            root_path, suffixes={ext for spec in SERVER_SPECS for ext in spec.extensions}, limit=100
        )
    )
    diagnostics: list[dict[str, Any]] = []
    servers: set[str] = set()
    grouped: dict[LspServerSpec, list[Path]] = {}
    for path in files:
        if spec := _spec_for_path(path):
            grouped.setdefault(spec, []).append(path)
    for spec, paths in grouped.items():
        try:
            with _client(spec, root_path) as client:
                servers.add(spec.command[0])
                uri_paths: dict[str, Path] = {}
                for path in paths:
                    uri = client.open_document(path, _language_id(path, spec))
                    uri_paths[uri] = path
                notices = client.collect_notifications(
                    "textDocument/publishDiagnostics", timeout=min(client.timeout, 4)
                )
                for notice in notices:
                    params = notice.get("params") or {}
                    diagnostic_path = uri_paths.get(str(params.get("uri") or ""))
                    if diagnostic_path is None:
                        continue
                    diagnostics.extend(
                        _diagnostic(diagnostic_path, root_path, item)
                        for item in params.get("diagnostics", [])
                        if isinstance(item, dict)
                    )
        except LspError:
            continue
    if servers:
        return {
            "ok": not any(item["severity"] == "error" for item in diagnostics),
            "root": str(root_path),
            "diagnostics": diagnostics,
            "source": "lsp",
            "servers": sorted(servers),
        }
    return _fallback_diagnostics(root_path, "no server returned diagnostics")


def lsp_definition(root: str | Path, symbol: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    location = _find_symbol_position(root_path, symbol)
    result = _position_request(root_path, location, "textDocument/definition") if location else None
    if result and result["locations"]:
        return {
            "ok": True,
            "symbol": symbol,
            "definitions": result["locations"],
            "source": "lsp",
            "server": result["server"],
        }
    matches = [
        item
        for item in _fallback_symbols(root_path, symbol, "")["symbols"]
        if item["name"] == symbol
    ]
    return {
        "ok": bool(matches),
        "symbol": symbol,
        "definitions": matches[:20],
        "source": "ast-fallback",
        "fallback_reason": result["error"] if result else "symbol position not found",
    }


def lsp_references(root: str | Path, symbol: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    location = _find_symbol_position(root_path, symbol)
    result = (
        _position_request(
            root_path,
            location,
            "textDocument/references",
            {"context": {"includeDeclaration": True}},
        )
        if location
        else None
    )
    if result and result["locations"]:
        return {
            "ok": True,
            "symbol": symbol,
            "references": result["locations"][:500],
            "source": "lsp",
            "server": result["server"],
        }
    refs = _text_references(root_path, symbol)
    return {
        "ok": True,
        "symbol": symbol,
        "references": refs[:200],
        "source": "text-fallback",
        "fallback_reason": result["error"] if result else "symbol position not found",
    }


def lsp_hover(root: str | Path, path: str, line: int, column: int) -> dict[str, Any]:
    root_path = Path(root).resolve()
    result = _position_request(root_path, (root_path / path, line, column), "textDocument/hover")
    if not result:
        return {
            "ok": False,
            "source": "fallback-unavailable",
            "error": "hover requires an available LSP server",
        }
    return {"ok": True, "source": "lsp", "server": result["server"], "hover": result["raw"]}


def lsp_rename(
    root: str | Path, path: str, line: int, column: int, new_name: str
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    result = _position_request(
        root_path, (root_path / path, line, column), "textDocument/rename", {"newName": new_name}
    )
    if not result:
        return {
            "ok": False,
            "source": "fallback-unavailable",
            "error": "rename requires an available LSP server",
        }
    return {
        "ok": True,
        "source": "lsp",
        "server": result["server"],
        "workspace_edit": result["raw"],
    }


def _client(spec: LspServerSpec, root: Path) -> LspClient:
    initialization_options: dict[str, Any] = {}
    if spec.language == "typescript":
        tsserver = _typescript_server_library()
        if tsserver:
            initialization_options = {"tsserver": {"path": str(tsserver)}}
    return LspClient(
        list(spec.command),
        root,
        timeout=12,
        initialization_options=initialization_options,
    )


def _available(spec: LspServerSpec) -> bool:
    return bool(shutil.which(spec.command[0]))


def _first_available_spec(root: Path) -> LspServerSpec | None:
    suffixes = {
        path.suffix
        for path in iter_project_files(
            root, suffixes={ext for spec in SERVER_SPECS for ext in spec.extensions}, limit=200
        )
    }
    return next(
        (
            spec
            for spec in SERVER_SPECS
            if _available(spec) and suffixes.intersection(spec.extensions)
        ),
        None,
    )


def _spec_for_path(path: Path) -> LspServerSpec | None:
    return next(
        (spec for spec in SERVER_SPECS if path.suffix in spec.extensions and _available(spec)), None
    )


def _position_request(
    root: Path,
    location: tuple[Path, int, int] | None,
    method: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not location:
        return None
    path, line, column = location
    spec = _spec_for_path(path)
    if not spec:
        return None
    try:
        with _client(spec, root) as client:
            uri = client.open_document(path, _language_id(path, spec))
            params = {
                "textDocument": {"uri": uri},
                "position": {"line": max(0, line - 1), "character": max(0, column - 1)},
                **(extra or {}),
            }
            raw = client.request(method, params)
            return {"server": spec.command[0], "raw": raw, "locations": _locations(raw, root)}
    except LspError as exc:
        return {"server": spec.command[0], "raw": None, "locations": [], "error": str(exc)}


def _locations(value: Any, root: Path) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    locations = []
    for item in items:
        target = item.get("targetUri") or item.get("uri")
        position = (item.get("targetSelectionRange") or item.get("range") or {}).get("start") or {}
        if target:
            path = _uri_path(str(target))
            locations.append(
                {
                    "path": _relative(path, root),
                    "line": int(position.get("line", 0)) + 1,
                    "column": int(position.get("character", 0)) + 1,
                }
            )
    return locations


def _symbol(item: dict[str, Any], root: Path) -> dict[str, Any]:
    location = item.get("location") or {}
    position = (location.get("range") or {}).get("start") or {}
    return {
        "name": str(item.get("name") or ""),
        "kind": item.get("kind"),
        "path": _relative(_uri_path(str(location.get("uri") or "")), root),
        "line": int(position.get("line", 0)) + 1,
        "column": int(position.get("character", 0)) + 1,
    }


def _diagnostic(path: Path, root: Path, item: dict[str, Any]) -> dict[str, Any]:
    start = (item.get("range") or {}).get("start") or {}
    severity_value = item.get("severity")
    severity = {1: "error", 2: "warning", 3: "information", 4: "hint"}.get(
        severity_value if isinstance(severity_value, int) else 2,
        "warning",
    )
    return {
        "path": _relative(path, root),
        "line": int(start.get("line", 0)) + 1,
        "column": int(start.get("character", 0)) + 1,
        "severity": severity,
        "message": str(item.get("message") or ""),
        "code": item.get("code"),
    }


def _fallback_symbols(root: Path, query: str, reason: str) -> dict[str, Any]:
    symbols = []
    q = query.lower()
    for path in iter_project_files(root, suffixes={".py"}, limit=1500):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                item = {
                    "name": node.name,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "path": rel,
                    "line": node.lineno,
                }
                if not q or q in node.name.lower() or q in rel.lower():
                    symbols.append(item)
    return {
        "ok": True,
        "root": str(root),
        "symbols": symbols[:500],
        "source": "ast-fallback",
        "fallback_reason": reason,
    }


def _fallback_diagnostics(root: Path, reason: str) -> dict[str, Any]:
    diagnostics = []
    for path in iter_project_files(root, suffixes={".py"}, limit=1500):
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except SyntaxError as exc:
            diagnostics.append(
                {
                    "path": _relative(path, root),
                    "line": exc.lineno or 0,
                    "column": exc.offset or 0,
                    "severity": "error",
                    "message": exc.msg,
                }
            )
        except Exception as exc:
            diagnostics.append(
                {
                    "path": _relative(path, root),
                    "line": 0,
                    "column": 0,
                    "severity": "warning",
                    "message": str(exc),
                }
            )
    return {
        "ok": not diagnostics,
        "root": str(root),
        "diagnostics": diagnostics,
        "source": "ast-fallback",
        "fallback_reason": reason,
    }


def _find_symbol_position(root: Path, symbol: str) -> tuple[Path, int, int] | None:
    for path in iter_project_files(
        root, suffixes={ext for spec in SERVER_SPECS for ext in spec.extensions}, limit=2000
    ):
        for index, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            column = line.find(symbol)
            if column >= 0:
                return path, index, column + 1
    return None


def _text_references(root: Path, symbol: str) -> list[dict[str, Any]]:
    refs = []
    for path in iter_project_files(
        root, suffixes={".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go"}, limit=2000
    ):
        for index, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if symbol in line:
                refs.append(
                    {"path": _relative(path, root), "line": index, "text": line.strip()[:240]}
                )
    return refs


def _uri_path(uri: str) -> Path:
    parsed = urlparse(uri)
    return Path(unquote(parsed.path)).resolve()


def _language_id(path: Path, spec: LspServerSpec) -> str:
    return {
        ".tsx": "typescriptreact",
        ".js": "javascript",
        ".jsx": "javascriptreact",
    }.get(path.suffix, spec.language)


def _typescript_server_library() -> Path | None:
    executable = shutil.which("typescript-language-server")
    if not executable:
        return None
    resolved = Path(executable).resolve()
    candidates = (
        resolved.parents[2] / "typescript" / "lib" / "tsserverlibrary.js",
        resolved.parents[2] / "typescript" / "lib" / "tsserver.js",
    )
    return next((path for path in candidates if path.exists()), None)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
