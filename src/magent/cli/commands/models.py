"""Provider, model-role and credential (`auth`) command groups."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import NoReturn

import typer
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from magent.cli import shared
from magent.cli.app import (
    auth_app,
    model_app,
    provider_app,
)
from magent.cli.command_context import (
    store,
)
from magent.cli.shared import console
from magent.config import (
    get_current_user,
    load_config,
)


@provider_app.command("list")
def provider_list_cmd():
    """List known providers and default models."""
    from magent.config_ux import provider_access_modes, provider_choices

    table = Table("Provider", "Default Model", "Access", "Description")
    for item in provider_choices():
        access = ", ".join(mode["id"] for mode in provider_access_modes(item["id"]))
        table.add_row(item["id"], item["default_model"], access, item["label"])
    console.print(table)


@provider_app.command("detect")
def provider_detect_cmd():
    """Detect likely provider readiness from local defaults and env vars."""
    from magent.config_ux import detect_provider_environment

    console.print_json(data={"ok": True, "providers": detect_provider_environment()})


@provider_app.command("set")
def provider_set_cmd(
    provider_id: str = typer.Argument(...),
    model: str | None = typer.Option(None, "--model", "-m"),
    api_key_env: str = typer.Option("", "--api-key-env"),
    api_key: str = typer.Option("", "--api-key"),
    api_key_keyring: str = typer.Option("", "--api-key-keyring"),
    base_url: str = typer.Option("", "--base-url"),
    team_id: str = typer.Option("", "--team-id", help="Optional provider team identifier"),
    access_mode: str = typer.Option(
        "", "--access", help="api, codex, payg, subscription, or local"
    ),
):
    """Set the default provider and model without editing config.toml."""
    from magent.config_ux import set_default_provider

    console.print_json(
        data=set_default_provider(
            provider_id,
            model,
            api_key_env=api_key_env,
            api_key=api_key,
            api_key_keyring=api_key_keyring,
            base_url=base_url,
            access_mode=access_mode,
            team_id=team_id,
        )
    )


@provider_app.command("wizard")
def provider_wizard_cmd():
    """Interactively configure provider, access mode, model, and key source."""
    from magent.cli.model_picker import prompt_for_provider_model
    from magent.cli.wizard_guidance import explain_options
    from magent.config_ux import provider_access_modes, provider_choices, set_default_provider
    from magent.provider_catalog import provider_env_vars

    console.print(
        Panel(
            "Choose the service used for ordinary MagAgent requests, how you access it, where its "
            "credential lives, and a model exposed by that provider.",
            title="Provider Wizard",
        )
    )
    choices = provider_choices()
    for i, item in enumerate(choices, 1):
        console.print(f"{i}. {item['id']} — {item['label']}")
    choice = Prompt.ask("Provider number", default="1")
    try:
        selected = choices[int(choice) - 1]
    except (ValueError, IndexError):
        selected = choices[0]
    modes = provider_access_modes(selected["id"])
    explain_options(
        console,
        "Access modes",
        [
            (str(i), f"{item['label']}: {item.get('description', item['id'])}")
            for i, item in enumerate(modes, 1)
        ],
        note="Access mode determines authentication and billing; it does not merely rename the provider.",
    )
    access_choice = Prompt.ask("Access mode", default="1")
    try:
        access_mode = modes[int(access_choice) - 1]["id"]
    except (ValueError, IndexError):
        access_mode = modes[0]["id"]
    team_id = ""
    if selected["id"] == "prime-intellect":
        team_id = Prompt.ask("Prime Intellect team ID (optional)", default="").strip()
    api_key_env = ""
    api_key = ""
    if access_mode not in {"codex", "local"}:
        default_env = provider_env_vars().get(selected["id"], "")
        console.print("[dim]Choose how MagAgent should find this provider credential.[/dim]")
        console.print("  [cyan]1[/cyan]. Paste key now and save it in MagAgent config")
        console.print(f"  [cyan]2[/cyan]. Use environment variable [bold]{default_env}[/bold]")
        console.print("  [cyan]3[/cyan]. Skip for now")
        console.print(
            "[dim]Pasted keys are stored locally with restrictive file permissions and redacted in "
            "config output. Environment variables keep the secret outside MagAgent config.[/dim]"
        )
        credential_choice = Prompt.ask("Credential option", choices=["1", "2", "3"], default="1")
        if credential_choice == "1":
            api_key = Prompt.ask("API key", password=True, default="").strip()
            if not api_key:
                console.print(
                    "[yellow]No key entered; falling back to environment variable setup.[/yellow]"
                )
                api_key_env = Prompt.ask("API key environment variable", default=default_env)
        elif credential_choice == "2":
            api_key_env = Prompt.ask("API key environment variable", default=default_env)
        else:
            console.print(
                f"[yellow]Skipping credential. You can add one later with "
                f"[bold]magent provider wizard[/bold] or [bold]magent provider set {selected['id']} --api-key-env {default_env}[/bold].[/yellow]"
            )
    base_url = ""
    if selected["id"] == "custom":
        base_url = Prompt.ask("API base URL", default="http://localhost:8000/v1").strip()
    resolved_key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
    model = prompt_for_provider_model(
        load_config(get_current_user()),
        store(),
        selected["id"],
        default_model=selected["default_model"],
        api_key=resolved_key,
        base_url=base_url or None,
        console=console,
    )
    result = set_default_provider(
        selected["id"],
        model,
        api_key_env=api_key_env,
        api_key=api_key,
        base_url=base_url,
        access_mode=access_mode,
        team_id=team_id,
    )
    console.print_json(data=result)


@provider_app.command("test")
def provider_test_cmd(
    provider_id: str | None = typer.Argument(None),
    model: str | None = typer.Option(None, "--model", "-m"),
):
    """Test a provider/model connection."""
    from magent.providers import test_provider

    username = get_current_user()
    config = load_config(username)
    provider_obj = shared._build_provider(config, provider_id, model)

    async def _run():
        return await test_provider(provider_obj)

    ok = asyncio.run(_run())
    console.print_json(
        data={
            "ok": ok,
            "provider": provider_obj.provider_id,
            "model": provider_obj.model,
        }
    )
    if not ok:
        raise typer.Exit(1)


@provider_app.command("doctor")
def provider_doctor_cmd():
    """Show provider, model-role, memory, gateway, and subagent readiness."""
    from magent.config_ux import ux_doctor

    console.print_json(data=ux_doctor(get_current_user()))


@provider_app.command("cooldowns")
def provider_cooldowns_cmd():
    """Show providers currently paused due to rate limits."""
    from magent.provider_cooldown import list_provider_cooldowns

    console.print_json(data=list_provider_cooldowns())


@provider_app.command("clear-cooldown")
def provider_clear_cooldown_cmd(provider_id: str = typer.Argument(...)):
    """Clear a provider cooldown."""
    from magent.provider_cooldown import clear_provider_cooldown

    console.print_json(data=clear_provider_cooldown(provider_id))


@model_app.command("roles")
def model_roles_cmd():
    """Show configured model roles."""
    from magent.config_ux import model_role_summary

    console.print_json(data=model_role_summary())


@model_app.command("set-role")
def model_set_role_cmd(role: str = typer.Argument(...), value: str = typer.Argument(...)):
    """Set a model role, e.g. coding openai/gpt-5."""
    from magent.config_ux import set_model_role

    result = set_model_role(role, value)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("clear-role")
def model_clear_role_cmd(role: str = typer.Argument(...)):
    """Clear a configured model role."""
    from magent.config_ux import clear_model_role

    result = clear_model_role(role)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("doctor")
def model_doctor_cmd():
    """Show model role readiness."""
    from magent.config_ux import ux_doctor

    console.print_json(
        data={"ok": True, "model_roles": ux_doctor(get_current_user())["model_roles"]}
    )


@model_app.command("orchestration-doctor")
def model_orchestration_doctor_cmd(
    planning_role: str = typer.Option("review", "--planning-role"),
    execution_role: str = typer.Option("coding", "--execution-role"),
):
    """Show planning/execution role readiness for orchestrated goals."""
    from magent.config_ux import orchestration_role_doctor

    result = orchestration_role_doctor(planning_role=planning_role, execution_role=execution_role)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("health")
def model_health_cmd():
    """Show model role provider/runtime health and recent live smoke observations."""
    from magent.config_ux import model_role_health
    from magent.model_health import model_health_report

    result = model_role_health()
    result["observations"] = model_health_report(shared._store())
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("capabilities")
def model_capabilities_cmd():
    """Show capability metadata for configured model roles."""
    from magent.model_capabilities import role_capability_summary

    config = load_config(get_current_user())
    console.print_json(data={"ok": True, "roles": role_capability_summary(config)})


@model_app.command("recommend")
def model_recommend_cmd(
    provider: str | None = typer.Option(None, "--provider", "-p"),
    task_type: str = typer.Option("tool-use", "--task-type", "-t"),
):
    """Recommend a model from successful local health observations."""
    from magent.model_health import recommend_model_from_health

    result = recommend_model_from_health(shared._store(), provider=provider, task_type=task_type)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@model_app.command("wizard")
def model_wizard_cmd():
    """Explain and configure specialized model roles."""
    from magent.cli.wizard_guidance import explain_options
    from magent.config_ux import MODEL_ROLES, set_model_role

    config = load_config(get_current_user())
    default = f"{config.default_provider}/{config.default_model}"
    explain_options(
        console,
        "Model roles",
        [
            ("coding", "Primary implementation and tool-use work."),
            ("review", "Independent code and change review."),
            ("memory", "Conversation-memory extraction and summarization."),
            ("cheap", "Low-cost background, routing, and lightweight tasks."),
            ("image_maker", "Image-generation requests when the provider supports them."),
            ("fallback", "Backup model used when the preferred model is unavailable."),
        ],
        note="Use provider/model values. Press Enter to inherit the displayed default; leave fallback blank to disable it.",
    )
    results = []
    for role in MODEL_ROLES:
        value = Prompt.ask(f"{role} model", default=default if role != "fallback" else "")
        if value:
            results.append(set_model_role(role, value))
    console.print_json(data={"ok": all(item.get("ok") for item in results), "results": results})


@model_app.command("image-wizard")
def model_image_wizard_cmd():
    """Interactively configure the image_maker model role and credentials."""
    from magent.cli.wizard_guidance import explain_field
    from magent.config_ux import (
        configure_provider_entry,
        image_model_choices,
        set_model_role,
    )
    from magent.provider_catalog import provider_env_vars

    explain_field(
        console,
        "Image model role",
        "Used only by image-generation tools. It does not replace your default chat or coding model.",
    )
    choices = image_model_choices()
    for i, item in enumerate(choices, 1):
        default = item["value"] or "provider/model"
        console.print(f"{i}. {item['label']} — {default}")
    choice = Prompt.ask("Image model", default="1")
    try:
        selected = choices[int(choice) - 1]
    except (ValueError, IndexError):
        selected = choices[0]

    if selected["id"] == "custom":
        provider_id = Prompt.ask("Provider id", default="openai").strip()
        model = Prompt.ask("Image model name", default="gpt-image-1").strip()
        value = f"{provider_id}/{model}" if provider_id and model else ""
        access_mode = Prompt.ask("Access mode", default="api").strip()
        default_env = provider_env_vars().get(provider_id, "")
    else:
        provider_id = selected["provider"]
        model = selected["model"]
        value = selected["value"]
        access_mode = selected["access_mode"]
        default_env = selected["api_key_env"]

    if not value:
        console.print_json(data={"ok": False, "error": "Image model must be provider/model."})
        raise typer.Exit(1)

    api_key_env = ""
    api_key = ""
    console.print("[dim]Choose how MagAgent should find this image provider credential.[/dim]")
    console.print("  [cyan]1[/cyan]. Paste key now and save it in MagAgent config")
    console.print(
        f"  [cyan]2[/cyan]. Use environment variable [bold]{default_env or 'PROVIDER_API_KEY'}[/bold]"
    )
    console.print("  [cyan]3[/cyan]. Skip credential setup")
    credential_choice = Prompt.ask("Credential option", choices=["1", "2", "3"], default="2")
    if credential_choice == "1":
        api_key = Prompt.ask("API key", password=True, default="").strip()
        if not api_key:
            console.print(
                "[yellow]No key entered; falling back to environment variable setup.[/yellow]"
            )
            api_key_env = Prompt.ask("API key environment variable", default=default_env)
    elif credential_choice == "2":
        api_key_env = Prompt.ask("API key environment variable", default=default_env)

    provider_result = configure_provider_entry(
        provider_id,
        model=model,
        api_key_env=api_key_env,
        api_key=api_key,
        access_mode=access_mode,
    )
    role_result = set_model_role("image_maker", value)
    result = {
        "ok": bool(provider_result.get("ok") and role_result.get("ok")),
        "provider": provider_result,
        "role": role_result,
        "next": "Run `magent model health` to verify credential readiness.",
    }
    console.print_json(data=result)
    if not result["ok"]:
        raise typer.Exit(1)


@auth_app.command("list")
def auth_list_cmd():
    """List configured provider credential sources."""
    from magent.auth_store import keyring_status, list_auth_entries

    config = load_config(get_current_user())
    status = keyring_status()
    console.print_json(
        data={
            "ok": True,
            "keyring_available": status["available"],
            "keyring": status,
            "credentials": list_auth_entries(config.providers),
        }
    )


@auth_app.command("add")
def auth_add_cmd(
    provider_id: str = typer.Argument(..., help="Provider id, e.g. nous-portal or openai."),
    api_key_stdin: bool = typer.Option(
        False,
        "--api-key-stdin",
        help="Read the key from standard input (non-interactive; never via argv).",
    ),
    storage: str = typer.Option(
        "keyring",
        "--storage",
        help="Where to keep the key: keyring (OS credential store) or config (0600 config.toml).",
    ),
    api_key: str = typer.Option(
        "",
        "--api-key",
        help="Deprecated: a key on the command line is visible to other processes "
        "and shell history. Use --api-key-stdin.",
        hidden=True,
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Accepted for scripts; the result is always JSON."
    ),
):
    """Store a provider API key without printing it.

    Interactive: `magent auth add openai` prompts with hidden input.

    Scripts and desktop apps pipe the key over stdin so it never appears in
    argv or shell history:

      printf '%s' "$KEY" | magent auth add nous-portal --api-key-stdin

      printf '%s' "$KEY" | magent auth add openai --api-key-stdin --storage config

    Exit codes: 0 stored, 1 storage failed, 2 usage error (unknown provider,
    empty stdin, stdin is a terminal, conflicting options).
    """
    from magent.auth_store import store_provider_secret

    del json_output  # the result is JSON either way

    def usage_error(message: str, hint: str = "") -> NoReturn:
        payload = {"ok": False, "provider": provider_id, "error": message}
        if hint:
            payload["hint"] = hint
        console.print_json(data=payload)
        raise typer.Exit(2)

    storage_choice = storage.strip().lower()
    if storage_choice not in {"keyring", "config"}:
        usage_error("--storage must be keyring or config.")
    if api_key_stdin and api_key:
        usage_error("Use either --api-key-stdin or --api-key, not both.")

    from magent.provider_catalog import canonical_provider_id, provider_metadata

    canonical = canonical_provider_id(provider_id)
    config = load_config(get_current_user())
    if not provider_metadata(canonical) and canonical not in (config.providers or {}):
        usage_error(
            f"Unknown provider: {provider_id}",
            "List providers with `magent provider matrix`; configure a custom endpoint "
            "with `magent provider set <id> --base-url <url>`.",
        )
    if provider_metadata(canonical).get("local"):
        usage_error(f"{canonical} runs locally and does not use an API key.")

    source = "prompt"
    if api_key_stdin:
        if sys.stdin is None or sys.stdin.isatty():
            usage_error(
                "--api-key-stdin expects the key on standard input, but stdin is a terminal.",
                "Pipe it in, e.g. printf '%s' \"$KEY\" | magent auth add "
                f"{canonical} --api-key-stdin",
            )
        secret = sys.stdin.read().strip()
        source = "stdin"
        if not secret:
            usage_error("No key was received on standard input.")
    elif api_key:
        source = "argv"
        secret = api_key.strip()
        print(
            "Warning: --api-key exposes the key to process listings and shell history; "
            "use --api-key-stdin instead.",
            file=sys.stderr,
        )
    else:
        if sys.stdin is None or not sys.stdin.isatty():
            usage_error(
                "No key given and no terminal to prompt on.",
                f"Pipe the key in with `magent auth add {canonical} --api-key-stdin`.",
            )
        secret = typer.prompt(f"API key for {canonical}", hide_input=True, default="").strip()
        if not secret:
            usage_error("No key entered.")

    result = store_provider_secret(canonical, secret, storage=storage_choice)
    result["source"] = source
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@auth_app.command("remove")
def auth_remove_cmd(provider_id: str = typer.Argument(...)):
    """Remove a stored provider API key (keyring entry and config.toml copy)."""
    from magent.auth_store import delete_keyring_secret, keyring_available
    from magent.config import load_global_config, save_global_config
    from magent.provider_catalog import canonical_provider_id

    provider_id = canonical_provider_id(provider_id)
    cfg = load_global_config()
    # Only touch a provider that was actually configured: setdefault created an
    # empty entry for providers that never existed, which then showed up as
    # `configured: true`.
    providers = cfg.get("providers") or {}
    entry = providers.get(provider_id)
    removed_config = False
    referenced_keyring = False
    if isinstance(entry, dict):
        referenced_keyring = entry.pop("api_key_keyring", None) is not None
        removed_config = entry.pop("api_key", None) is not None
        if referenced_keyring or removed_config:
            save_global_config(cfg)
    if keyring_available():
        result = delete_keyring_secret(provider_id)
    else:
        result = {"ok": not referenced_keyring, "provider": provider_id, "deleted": False}
        if referenced_keyring:
            result["error"] = (
                "Config referenced a keyring entry, but no keyring is available to delete it."
            )
    result["removed_from_config"] = removed_config
    result["ok"] = bool(result.get("ok")) or removed_config
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)
