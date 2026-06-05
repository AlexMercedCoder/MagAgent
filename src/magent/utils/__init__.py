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

    ok = sys.version_info >= (3, 11)
    checks.append(("Python >= 3.11", ok, f"Python {sys.version.split()[0]}"))

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
    from magent.config import CONFIG_DIR, get_current_user, load_config, user_memory_dir

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

    if user:
        memory_dir = user_memory_dir(user)
        checks.append(("Memory directory", memory_dir.exists(), str(memory_dir)))
        try:
            import maggraph

            index = maggraph.open_index(str(memory_dir))
            checks.append(("MagGraph open", True, f"{len(index)} node(s)"))
        except Exception as e:
            checks.append(("MagGraph open", False, str(e)))

        cfg = load_config(user)
        provider_id = cfg.default_provider
        provider_cfg = cfg.provider_config(provider_id)
        checks.append(("Default provider", bool(provider_id), provider_id or "not configured"))
        if provider_cfg.get("api_key_env"):
            import os

            env = provider_cfg["api_key_env"]
            checks.append((f"{provider_id} API key env", bool(os.environ.get(env)), env))

        raw_cfg = cfg.as_dict()
        gateway_cfg = raw_cfg.get("gateway", {})
        checks.append(
            (
                "Gateway config",
                bool(gateway_cfg),
                "configured" if gateway_cfg else "not configured",
            )
        )
        mcp_cfg = raw_cfg.get("mcp", {}).get("servers", {})
        checks.append(
            (
                "MCP servers",
                isinstance(mcp_cfg, dict),
                f"{len(mcp_cfg)} configured" if isinstance(mcp_cfg, dict) else "invalid config",
            )
        )
        try:
            importlib.import_module("mcp")
            checks.append(("MCP SDK", True, "installed"))
        except ImportError:
            checks.append(("MCP SDK", not mcp_cfg, "install with: pip install 'mag-agent[mcp]'"))

    # ripgrep (optional)
    rg = shutil.which("rg")
    checks.append(("ripgrep (optional)", bool(rg), rg or "not found — search fallback to grep"))

    # git
    git = shutil.which("git")
    checks.append(("git", bool(git), git or "NOT FOUND"))

    maggraph_cli = shutil.which("maggraph")
    checks.append(("MagGraph CLI", bool(maggraph_cli), maggraph_cli or "not found"))

    # Print results
    t = Table("Check", "Status", "Details")
    for name, ok, detail in checks:
        status = "[green]✓ OK[/green]" if ok else "[red]✗ FAIL[/red]"
        t.add_row(name, status, detail)
    console.print(t)
