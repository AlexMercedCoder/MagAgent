"""LSP code intelligence command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_lsp_commands(lsp_app: typer.Typer) -> None:
    @lsp_app.command("status")
    def lsp_status_cmd() -> None:
        """Show detected language-server commands."""
        from magent.lsp import lsp_status

        console.print_json(data=lsp_status())

    @lsp_app.command("symbols")
    def lsp_symbols_cmd(query: str = typer.Option("", "--query", "-q"), project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show symbols using LSP when available, with AST fallback."""
        from magent.lsp import lsp_symbols

        console.print_json(data=lsp_symbols(project, query=query))

    @lsp_app.command("diagnostics")
    def lsp_diagnostics_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show diagnostics using available local tooling."""
        from magent.lsp import lsp_diagnostics

        result = lsp_diagnostics(project)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @lsp_app.command("definition")
    def lsp_definition_cmd(symbol: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")) -> None:
        """Find symbol definitions."""
        from magent.lsp import lsp_definition

        console.print_json(data=lsp_definition(project, symbol))

    @lsp_app.command("references")
    def lsp_references_cmd(symbol: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")) -> None:
        """Find text references to a symbol."""
        from magent.lsp import lsp_references

        console.print_json(data=lsp_references(project, symbol))
