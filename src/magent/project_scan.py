"""Shared bounded project file scanning helpers."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}


def ignored_path(path: Path, ignore_dirs: set[str] | None = None) -> bool:
    """Return true when a path is in an ignored/generated directory."""
    ignored = ignore_dirs or DEFAULT_IGNORE_DIRS
    return bool(set(path.parts) & ignored)


def iter_project_files(
    root: str | Path,
    *,
    suffixes: set[str] | None = None,
    names: set[str] | None = None,
    limit: int = 2000,
    ignore_dirs: set[str] | None = None,
) -> Iterable[Path]:
    """Yield project files with a limit, preferring git-tracked files when possible."""
    root_path = Path(root).resolve()
    yielded = 0
    for path in _git_files(root_path) or _walk_files(root_path):
        if yielded >= limit:
            break
        if ignored_path(path, ignore_dirs) or not path.is_file():
            continue
        if suffixes and path.suffix not in suffixes and path.name not in (names or set()):
            continue
        if names and not suffixes and path.name not in names:
            continue
        yielded += 1
        yield path


def scan_estimate(root: str | Path, *, limit: int = 5000) -> dict[str, int | bool]:
    """Return a cheap bounded estimate of project size."""
    root_path = Path(root).resolve()
    count = 0
    latest = 0
    truncated = False
    for count, path in enumerate(iter_project_files(root_path, limit=limit + 1), start=1):
        if count > limit:
            truncated = True
            break
        try:
            latest = max(latest, int(path.stat().st_mtime))
        except OSError:
            continue
    return {"files_seen": min(count, limit), "limit": limit, "truncated": truncated, "latest_mtime": latest}


def _git_files(root: Path) -> list[Path]:
    if not (root / ".git").exists():
        return []
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [root / line for line in result.stdout.splitlines() if line.strip()]


def _walk_files(root: Path) -> Iterable[Path]:
    yield from root.rglob("*")
