"""First-run setup wizard for MagAgent."""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from magent.config import (
    CONFIG_DIR,
    LOGS_DIR,
    SKILLS_DIR,
    USERS_DIR,
    create_user,
    get_current_user,
    load_global_config,
    save_global_config,
    set_current_user,
    user_exists,
)

console = Console()

PROVIDER_CHOICES = [
    ("opencode-go", "OpenCode Go (deepseek-v3-0324 — cheap, fast, great for coding)"),
    ("ollama", "Ollama (local — FREE, requires Ollama running)"),
    ("openai", "OpenAI (GPT-4o, GPT-5)"),
    ("anthropic", "Anthropic (Claude)"),
    ("nous-portal", "Nous Portal (Hermes 4 + 200+ models)"),
    ("opencode-zen", "OpenCode Zen (premium curated models)"),
    ("google", "Google Gemini"),
    ("groq", "Groq (fast inference)"),
    ("openrouter", "OpenRouter (aggregator)"),
    ("custom", "Custom OpenAI-compatible endpoint"),
]

DEFAULT_MODELS = {
    "opencode-go": "deepseek-v4-flash",
    "ollama": "qwen2.5-coder:32b",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
    "nous-portal": "nous-hermes-4",
    "opencode-zen": "deepseek-v4-flash",
    "google": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "deepseek/deepseek-chat",
    "custom": "your-model-name",
}


def run_setup() -> None:
    """Interactive first-run setup wizard."""
    console.print(Panel(
        "[bold magenta]Welcome to MagAgent Setup![/bold magenta]\n\n"
        "This wizard will configure your agent in under 2 minutes.",
        border_style="magenta",
    ))

    # Create config directories
    for d in [CONFIG_DIR, USERS_DIR, SKILLS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    console.print("[dim]✓ Config directories created[/dim]")

    # Create a user
    existing = get_current_user()
    if existing:
        console.print(f"[dim]Active user: [bold]{existing}[/bold][/dim]")
        change = Confirm.ask("Create a new user?", default=False)
        if not change:
            username = existing
        else:
            username = _prompt_create_user()
    else:
        username = _prompt_create_user()

    # Configure a provider
    console.print("\n[bold]Step 2: Choose your default AI provider[/bold]")
    for i, (pid, label) in enumerate(PROVIDER_CHOICES, 1):
        console.print(f"  [cyan]{i}[/cyan]. {label}")

    choice = Prompt.ask(
        "Enter number",
        default="1",
    )
    try:
        idx = int(choice) - 1
        provider_id, _ = PROVIDER_CHOICES[idx]
    except (ValueError, IndexError):
        provider_id = "ollama"

    default_model = DEFAULT_MODELS.get(provider_id, "unknown")
    model = Prompt.ask(f"Default model", default=default_model)

    # Get API key
    api_key_env = _get_api_key(provider_id)

    # Custom base URL for custom provider
    base_url = None
    if provider_id == "custom":
        base_url = Prompt.ask("API base URL", default="http://localhost:8000/v1")

    # Memory extraction model
    console.print("\n[bold]Step 3: Memory extraction model (can be different from main model)[/bold]")
    console.print("[dim]A smaller/cheaper model can be used to extract memories after conversations.[/dim]")
    same_as_main = Confirm.ask("Use same model for memory extraction?", default=True)
    if same_as_main:
        extract_provider = provider_id
        extract_model = model
    else:
        extract_provider = Prompt.ask("Extraction provider", default="ollama")
        extract_model = Prompt.ask("Extraction model", default="qwen2.5:7b")

    # Build and save config
    cfg = load_global_config()
    cfg["defaults"]["provider"] = provider_id
    cfg["defaults"]["model"] = model
    cfg["memory"]["extraction_provider"] = extract_provider
    cfg["memory"]["extraction_model"] = extract_model

    provider_entry: dict = {}
    if api_key_env:
        provider_entry["api_key_env"] = api_key_env
    if base_url:
        provider_entry["base_url"] = base_url
    provider_entry["default_model"] = model

    cfg.setdefault("providers", {})[provider_id] = provider_entry
    save_global_config(cfg)
    console.print("[dim]✓ Config saved[/dim]")

    # Smoke test
    console.print("\n[bold]Step 4: Testing provider connection...[/bold]")
    _smoke_test(provider_id, model, api_key_env, base_url)

    console.print(Panel(
        f"[bold green]✓ Setup complete![/bold green]\n\n"
        f"  User:     [bold]{username}[/bold]\n"
        f"  Provider: [bold]{provider_id}[/bold] / {model}\n\n"
        f"Run [bold]magent[/bold] to start your first session.",
        border_style="green",
    ))


def _prompt_create_user() -> str:
    while True:
        name = Prompt.ask("\n[bold]Step 1:[/bold] Choose a username")
        name = name.strip().lower().replace(" ", "_")
        if not name:
            console.print("[red]Username cannot be empty.[/red]")
            continue
        if user_exists(name):
            console.print(f"[yellow]User '{name}' already exists. Switching to it.[/yellow]")
            set_current_user(name)
            return name
        create_user(name)
        set_current_user(name)
        console.print(f"[green]✓ Created user [bold]{name}[/bold][/green]")
        return name


def _get_api_key(provider_id: str) -> str | None:
    """Prompt for API key env var name for non-local providers."""
    local = {"ollama", "lmstudio", "custom"}
    if provider_id in local:
        return None

    env_var_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "nous-portal": "NOUS_API_KEY",
        "opencode-zen": "OPENCODE_ZEN_KEY",
        "google": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    default_env = env_var_map.get(provider_id, f"{provider_id.upper().replace('-', '_')}_API_KEY")

    import os
    if os.environ.get(default_env):
        console.print(f"[dim]✓ Found {default_env} in environment[/dim]")
        return default_env

    console.print(f"\n[dim]Set your API key in the environment variable: [bold]{default_env}[/bold][/dim]")
    console.print(f"[dim]  export {default_env}=your-key-here[/dim]")
    return default_env


def _smoke_test(provider_id: str, model: str, api_key_env: str | None, base_url: str | None):
    import os
    from magent.providers import build_provider, test_provider

    api_key = os.environ.get(api_key_env) if api_key_env else None
    p_cfg = {}
    if base_url:
        p_cfg["base_url"] = base_url

    provider = build_provider(provider_id, model, api_key, p_cfg)

    async def _run():
        return await test_provider(provider)

    try:
        ok = asyncio.get_event_loop().run_until_complete(_run())
        if ok:
            console.print("[green]✓ Provider responded successfully[/green]")
        else:
            console.print("[yellow]⚠ Provider did not respond. Check your API key / connection.[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not test provider: {e}[/yellow]")
