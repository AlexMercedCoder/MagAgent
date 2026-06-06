"""Token-efficient repository map generation."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from magent.project_scan import iter_project_files
from magent.tokens import estimate_tokens, truncate_to_tokens

IGNORE_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "target",
}

IMPORTANT_FILES = {
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "README.md",
    "Makefile",
}

SOURCE_EXTS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".md",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
}


@dataclass
class RepoMapEntry:
    path: str
    symbols: list[str]
    score: float = 0.0

    def render(self) -> str:
        if self.symbols:
            return f"- `{self.path}`: {', '.join(self.symbols[:12])}"
        return f"- `{self.path}`"


class RepoMapCache:
    """Caches a compact project map and returns relevant slices per query."""

    def __init__(self, root: str | Path, max_files: int = 500):
        self.root = Path(root).resolve()
        self.max_files = max_files
        self._entries: list[RepoMapEntry] = []
        self._fingerprint: tuple[int, int] | None = None

    def relevant_slice(self, query: str, max_tokens: int = 1200) -> str:
        if max_tokens <= 0:
            return ""
        self._refresh_if_needed()
        if not self._entries:
            return ""

        query_words = _words(query)
        scored = []
        for entry in self._entries:
            haystack = _words(entry.path + " " + " ".join(entry.symbols))
            score = len(query_words & haystack)
            if Path(entry.path).name in IMPORTANT_FILES:
                score += 1
            scored.append(RepoMapEntry(entry.path, entry.symbols, float(score)))

        scored.sort(key=lambda e: (e.score, -len(e.path)), reverse=True)
        selected = [entry for entry in scored if entry.score > 0][:40] or scored[:25]

        lines = [
            "## Repository Map",
            "",
            f"Root: `{self.root}`",
            f"Files indexed: {len(self._entries)}",
            "",
        ]
        for entry in selected:
            lines.append(entry.render())
        rendered = "\n".join(lines)
        return truncate_to_tokens(rendered, max_tokens, "[...repo map truncated...]")

    def _refresh_if_needed(self) -> None:
        fingerprint = self._compute_fingerprint()
        if fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint
        self._entries = self._scan()

    def _compute_fingerprint(self) -> tuple[int, int]:
        latest = 0
        count = 0
        for path in self._iter_files(limit=2000):
            count += 1
            try:
                latest = max(latest, int(path.stat().st_mtime))
            except OSError:
                continue
        return count, latest

    def _scan(self) -> list[RepoMapEntry]:
        entries: list[RepoMapEntry] = []
        for path in self._iter_files(limit=self.max_files):
            rel = path.relative_to(self.root).as_posix()
            entries.append(RepoMapEntry(rel, _extract_symbols(path)))
        entries.sort(key=lambda entry: entry.path)
        return entries

    def _iter_files(self, limit: int):
        yield from iter_project_files(
            self.root,
            suffixes=SOURCE_EXTS,
            names=IMPORTANT_FILES,
            limit=limit,
            ignore_dirs=IGNORE_DIRS,
        )


def _words(text: str) -> set[str]:
    return set(re.sub(r"[^\w\s/.-]", " ", text.lower()).split())


def _extract_symbols(path: Path) -> list[str]:
    if path.suffix == ".py":
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return []
        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append(f"class {node.name}@{node.lineno}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                symbols.append(f"{prefix} {node.name}@{node.lineno}")
        symbols.sort(key=lambda item: int(item.rsplit("@", 1)[1]))
        return symbols[:24]

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    pattern = re.compile(
        r"^\s*(class|function|def|async def|export function|const|let|var|pub fn|fn)\s+([A-Za-z_][\w$]*)",
        re.MULTILINE,
    )
    symbols = [f"{match.group(1)} {match.group(2)}" for match in pattern.finditer(text)]
    if not symbols and path.name in IMPORTANT_FILES:
        symbols = [f"~{estimate_tokens(text)} tokens"]
    return symbols[:24]
