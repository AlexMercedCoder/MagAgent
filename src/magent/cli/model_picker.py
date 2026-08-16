"""Interactive provider-aware model selection."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from magent.provider_models import (
    discover_provider_models,
    filter_model_choices,
    ranked_model_choices,
)

MAX_VISIBLE_MODELS = 15


def prompt_for_provider_model(
    config: Any,
    store: Any,
    provider_id: str,
    *,
    default_model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    console: Console | None = None,
) -> str:
    """Discover and interactively choose a provider model.

    A model ID can always be entered directly. This matters for private,
    newly released, subscription-only, and custom models that a list endpoint
    may omit.
    """
    output = console or Console()
    with output.status(f"[bold]Loading models for {provider_id}...[/bold]"):
        result = discover_provider_models(
            config,
            store,
            provider_id,
            refresh=True,
            api_key=api_key,
            base_url=base_url,
        )
    models = ranked_model_choices(result.get("models", []), default_model=default_model)
    warning = str(result.get("warning") or "")
    if warning:
        output.print(f"[yellow]Model discovery: {warning}[/yellow]")

    if result.get("source") != "live" or len(models) <= 1:
        if models:
            output.print(
                f"[dim]Using the {result.get('source', 'catalog')} model suggestion; "
                "you can enter any supported model ID.[/dim]"
            )
        return Prompt.ask("Default model", default=default_model or (models[0] if models else ""))

    output.print(
        f"[green]Found {len(models)} models[/green] from the provider. "
        "Enter a number, a model ID, or [bold]/search text[/bold]."
    )
    query = ""
    while True:
        filtered = filter_model_choices(models, query)
        visible = filtered[:MAX_VISIBLE_MODELS]
        if not visible:
            output.print("[yellow]No model IDs matched that search.[/yellow]")
            query = ""
            continue

        table = Table("#", "Model", show_header=True)
        for index, model in enumerate(visible, 1):
            suffix = " [default]" if model == default_model else ""
            table.add_row(str(index), f"{model}{suffix}")
        output.print(table)
        if len(filtered) > len(visible):
            output.print(
                f"[dim]Showing {len(visible)} of {len(filtered)} matches. "
                "Use /search words to narrow the list.[/dim]"
            )

        answer = Prompt.ask("Model", default=_default_answer(visible, default_model)).strip()
        if answer.startswith("/"):
            query = answer[1:].strip()
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(visible):
            return visible[int(answer) - 1]
        if answer:
            return answer


def _default_answer(visible: list[str], default_model: str) -> str:
    if default_model in visible:
        return str(visible.index(default_model) + 1)
    return "1"
