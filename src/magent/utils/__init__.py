"""Utility helpers for MagAgent."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def human_bytes(n: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def run_doctor() -> None:
    """Run health checks and report status."""
    import importlib
    import shutil

    console.print(Panel("[bold]MagAgent Doctor[/bold]", border_style="cyan"))

    checks: list[tuple[str, bool, str]] = []

    # Python version
    import sys

    ok = sys.version_info >= (3, 12)
    checks.append(("Python >= 3.12", ok, f"Python {sys.version.split()[0]}"))

    # Dependencies
    for pkg, friendly in [
        ("typer", "Typer"),
        ("rich", "Rich"),
        ("litellm", "LiteLLM"),
        ("maggraph", "MagGraph"),
        ("httpx", "httpx"),
        ("yaml", "PyYAML"),
    ]:
        try:
            importlib.import_module(pkg)
            checks.append((friendly, True, "installed"))
        except ImportError:
            checks.append((friendly, False, "NOT INSTALLED — run: pip install magent"))

    # Config dir
    from magent.config import CONFIG_DIR, get_current_user

    checks.append(
        (
            "Config directory",
            CONFIG_DIR.exists(),
            str(CONFIG_DIR),
        )
    )

    # Active user
    user = get_current_user()
    checks.append(
        (
            "Active user",
            bool(user),
            user or "None — run: magent setup",
        )
    )

    # ripgrep (optional)
    rg = shutil.which("rg")
    checks.append(("ripgrep (optional)", bool(rg), rg or "not found — search fallback to grep"))

    # git
    git = shutil.which("git")
    checks.append(("git", bool(git), git or "NOT FOUND"))

    # Print results
    t = Table("Check", "Status", "Details")
    for name, ok, detail in checks:
        status = "[green]✓ OK[/green]" if ok else "[red]✗ FAIL[/red]"
        t.add_row(name, status, detail)
    console.print(t)
