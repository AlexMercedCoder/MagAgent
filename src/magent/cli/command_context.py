"""Shared CLI command helpers.

This module is the landing pad for command modules as they are extracted from
``magent.cli.main``. The main module keeps compatibility wrappers for tests and
older internal imports.
"""

from __future__ import annotations

import sys
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.prompt import Confirm

from magent.config import get_current_user, load_config, user_memory_dir
from magent.provider_catalog import provider_env_candidates, provider_metadata

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


def build_provider_for_role(config: Any, role: str):
    """Build a provider from a configured model role such as image_maker."""
    from magent.providers import build_provider as _build_provider

    p_id, m = config.provider_and_model_for_role(role)
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
        candidates = provider_env_candidates(provider_id, p_cfg.get("api_key_env", ""))
        raise ProviderCredentialError(provider_id, " or ".join(candidates) if candidates else env_var)


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


def fail(message: str, *, json_output: bool = False, code: int = 1, **extra: Any) -> NoReturn:
    """Report a command failure and exit.

    Three different failure idioms coexisted — printing red text then
    `raise typer.Exit(1)`, printing JSON with `ok: false`, and raising bare
    exceptions — so `--json` callers sometimes got a human string on stderr and
    sometimes a parseable object. This is the single idiom.
    """
    if json_output:
        console.print_json(data={"ok": False, "error": message, **extra})
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(code)


def confirm_or_exit(
    prompt: str,
    *,
    assume_yes: bool = False,
    default: bool = False,
    json_output: bool = False,
) -> None:
    """Ask for confirmation before a risky action, or exit.

    Confirmation was applied inconsistently — `plan-apply --sandbox` asked but
    `plan-sandbox` ran the same operations without asking.
    """
    if assume_yes:
        return
    if not sys.stdin.isatty():
        fail(
            f"{prompt} Refusing in a non-interactive session; pass --yes to proceed.",
            json_output=json_output,
        )
    if not Confirm.ask(prompt, default=default):
        fail("Cancelled.", json_output=json_output)


def _get_memory_manager():
    username = require_user()
    memory_dir = user_memory_dir(username)
    config = load_config(username)
    from magent.memory import MemoryManager

    return (
        MemoryManager(
            memory_dir,
            budget_tokens=config.memory_budget_tokens,
            max_node_tokens=config.recall_body_tokens,
            username=username,
            semantic_enabled=config.semantic_memory_enabled,
            semantic_provider=config.semantic_memory_provider,
            semantic_model=config.semantic_memory_model,
        ),
        username,
    )
