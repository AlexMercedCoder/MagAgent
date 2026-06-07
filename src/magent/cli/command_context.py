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
from magent.provider_catalog import provider_metadata

console = Console()


class ProviderCredentialError(RuntimeError):
    """Raised when a selected provider cannot authenticate from config."""

    def __init__(self, provider_id: str, env_var: str | None):
        self.provider_id = provider_id
        self.env_var = env_var
        if env_var:
            message = (
                f"Provider '{provider_id}' needs an API key, but {env_var} is not set. "
                f"Run `magent configure`, `magent provider set {provider_id} --api-key-env {env_var}`, "
                f"or export {env_var}=..."
            )
        else:
            message = (
                f"Provider '{provider_id}' needs credentials. Run `magent configure` "
                "or choose a local provider such as Ollama."
            )
        super().__init__(message)


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
    _ensure_provider_credentials(p_id, api_key, p_cfg)
    return _build_provider(p_id, m, api_key, p_cfg)


def build_extraction_provider(config: Any):
    from magent.providers import build_provider as _build_provider

    p_id = config.extraction_provider
    m = config.extraction_model
    api_key = config.resolve_api_key(p_id)
    p_cfg = config.provider_config(p_id)
    _ensure_provider_credentials(p_id, api_key, p_cfg)
    return _build_provider(p_id, m, api_key, p_cfg)


def _ensure_provider_credentials(provider_id: str, api_key: str | None, p_cfg: dict[str, Any]) -> None:
    metadata = provider_metadata(provider_id)
    if metadata.get("local") or metadata.get("access_mode") == "aws":
        return
    if api_key or p_cfg.get("api_key"):
        return
    env_var = p_cfg.get("api_key_env") or metadata.get("env")
    if env_var or metadata.get("env"):
        raise ProviderCredentialError(provider_id, env_var)


def known_command_names(app) -> list[str]:
    names = []
    _collect_command_names(app, "", names)
    return names


def _collect_command_names(typer_app: Any, prefix: str, names: list[str]) -> None:
    for command in typer_app.registered_commands:
        if command.name:
            names.append(f"{prefix} {command.name}".strip())
    for group_info in typer_app.registered_groups:
        if not group_info.name or not group_info.typer_instance:
            continue
        group_name = f"{prefix} {group_info.name}".strip()
        names.append(group_name)
        _collect_command_names(group_info.typer_instance, group_name, names)
