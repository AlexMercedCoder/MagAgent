"""Shared CLI command helpers.

This module is the landing pad for command modules as they are extracted from
``magent.cli.main``. The main module keeps compatibility wrappers for tests and
older internal imports.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.console import Console

from magent.config import get_current_user

console = Console()


def require_user() -> str:
    user = get_current_user()
    if not user:
        console.print(
            "[red]No active user. Run [bold]magent setup[/bold] or "
            "[bold]magent user create <name>[/bold] first.[/red]"
        )
        raise typer.Exit(1)
    return user


def store():
    from magent.workbench import WorkbenchStore

    return WorkbenchStore(require_user())


def build_provider(config: Any, provider_id: str | None, model: str | None):
    from magent.providers import build_provider as _build_provider

    p_id = provider_id or config.default_provider
    m = model or config.default_model
    api_key = config.resolve_api_key(p_id)
    p_cfg = config.provider_config(p_id)
    return _build_provider(p_id, m, api_key, p_cfg)


def build_extraction_provider(config: Any):
    from magent.providers import build_provider as _build_provider

    p_id = config.extraction_provider
    m = config.extraction_model
    api_key = config.resolve_api_key(p_id)
    p_cfg = config.provider_config(p_id)
    return _build_provider(p_id, m, api_key, p_cfg)


def known_command_names(app) -> list[str]:
    names = []
    for command in app.registered_commands:
        if command.name:
            names.append(command.name)
    for group_info in app.registered_groups:
        if not group_info.name or not group_info.typer_instance:
            continue
        names.append(group_info.name)
        for command in group_info.typer_instance.registered_commands:
            if command.name:
                names.append(f"{group_info.name} {command.name}")
    return names
