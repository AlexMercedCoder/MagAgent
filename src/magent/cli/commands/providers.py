"""Provider UX command registrations."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register_provider_ux_commands(provider_app: typer.Typer) -> None:
    @provider_app.command("matrix")
    def provider_matrix_cmd() -> None:
        """Show provider catalog, access mode, env, and configured state."""
        from magent.config_ux import provider_matrix

        table = Table("Provider", "Default Model", "Access", "Env", "Ready", "Configured")
        for item in provider_matrix()["providers"]:
            ready = "yes" if item["ready"] else "no"
            table.add_row(
                item["id"],
                item["default_model"],
                item["access_mode"],
                item["env"],
                ready,
                "yes" if item["configured"] else "no",
            )
        console.print(table)

    @provider_app.command("explain")
    def provider_explain_cmd(provider_id: str = typer.Argument(...)) -> None:
        """Explain one provider and show setup commands."""
        from magent.config_ux import provider_explain

        result = provider_explain(provider_id)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @provider_app.command("env")
    def provider_env_cmd() -> None:
        """Show provider environment variable readiness."""
        from magent.config_ux import provider_env_status

        console.print_json(data=provider_env_status())

    @provider_app.command("recommend")
    def provider_recommend_cmd(goal: str = typer.Option("coding", "--goal", "-g")) -> None:
        """Recommend providers for coding, review, cheap, local, memory, or research."""
        from magent.config_ux import provider_recommend

        console.print_json(data=provider_recommend(goal))

    @provider_app.command("catalog-doctor")
    def provider_catalog_doctor_cmd() -> None:
        """Validate provider catalog metadata."""
        from magent.config_ux import provider_catalog_doctor

        result = provider_catalog_doctor()
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @provider_app.command("test-matrix")
    def provider_test_matrix_cmd(
        all_providers: bool = typer.Option(False, "--all", help="Include providers that are not ready."),
    ) -> None:
        """Test configured/ready providers and report skipped providers."""
        from magent.cli.command_context import build_provider
        from magent.config import get_current_user, load_config
        from magent.config_ux import provider_matrix
        from magent.providers import test_provider

        username = get_current_user()
        config = load_config(username)
        rows = []
        for item in provider_matrix()["providers"]:
            ready = bool(item["ready"])
            configured = bool(item["configured"] or item["id"] == config.default_provider)
            should_test = configured and (ready or all_providers)
            if not should_test:
                rows.append(
                    {
                        "provider": item["id"],
                        "ready": ready,
                        "configured": configured,
                        "tested": False,
                        "ok": None,
                        "reason": "not configured or missing runtime/env",
                    }
                )
                continue
            provider_obj = build_provider(config, item["id"], item["default_model"])
            ok = asyncio.run(test_provider(provider_obj))
            rows.append(
                {
                    "provider": item["id"],
                    "ready": ready,
                    "configured": configured,
                    "tested": True,
                    "ok": ok,
                    "reason": "passed" if ok else "provider ping failed",
                }
            )
        console.print_json(data={"ok": all(row["ok"] is not False for row in rows), "providers": rows})

    @provider_app.command("models")
    def provider_models_cmd(
        provider_id: str = typer.Argument(..., help="Provider ID to inspect."),
        refresh: bool = typer.Option(False, "--refresh", help="Refresh from the live provider API."),
    ) -> None:
        """List cached or discovered models for a provider."""
        from magent.cli.command_context import require_user, store
        from magent.config import load_config
        from magent.provider_models import discover_provider_models

        username = require_user()
        console.print_json(
            data=discover_provider_models(load_config(username), store(), provider_id, refresh=refresh)
        )

    @provider_app.command("recommend-model")
    def provider_recommend_model_cmd(
        provider_id: str = typer.Argument(..., help="Provider ID to inspect."),
        goal: str = typer.Option("tool-use", "--goal", "-g"),
    ) -> None:
        """Recommend a model for a provider and goal."""
        from magent.cli.command_context import require_user, store
        from magent.config import load_config
        from magent.provider_models import recommend_provider_model

        username = require_user()
        console.print_json(
            data=recommend_provider_model(load_config(username), store(), provider_id, goal=goal)
        )

    @provider_app.command("tool-smoke")
    def provider_tool_smoke_cmd(
        provider_id: str = typer.Argument(..., help="Provider ID to test."),
        model: str | None = typer.Option(None, "--model", "-m", help="Model override."),
        project: str | None = typer.Option(
            None,
            "--project",
            "-p",
            help="Project directory for the smoke artifact. Defaults to a temporary directory.",
        ),
        timeout: int = typer.Option(90, "--timeout", help="Maximum smoke runtime in seconds."),
    ) -> None:
        """Run a tiny live tool-use smoke test against one provider."""
        from magent.cli.command_context import require_user, store
        from magent.config import load_config
        from magent.provider_smoke import run_provider_tool_smoke

        username = require_user()
        config = load_config(username)
        result = run_provider_tool_smoke(
            username=username,
            config=config,
            store=store(),
            provider_id=provider_id,
            model=model,
            project=project,
            timeout_seconds=timeout,
        )
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @provider_app.command("smoke-all")
    def provider_smoke_all_cmd(
        cheap: bool = typer.Option(True, "--cheap/--all-models", help="Use catalog cheap defaults."),
        timeout: int = typer.Option(90, "--timeout", help="Maximum smoke runtime per provider."),
    ) -> None:
        """Run tiny live tool-use smokes for configured ready providers."""
        from magent.cli.command_context import require_user, store
        from magent.config import load_config
        from magent.config_ux import provider_matrix
        from magent.provider_models import recommend_provider_model
        from magent.provider_smoke import run_provider_tool_smoke

        username = require_user()
        config = load_config(username)
        rows = []
        for item in provider_matrix()["providers"]:
            if not item["ready"] or not (item["configured"] or item["id"] == config.default_provider):
                continue
            recommendation = recommend_provider_model(config, store(), item["id"], goal="cheap")
            model = recommendation.get("model") if cheap and recommendation.get("ok") else item["default_model"]
            rows.append(
                run_provider_tool_smoke(
                    username,
                    config,
                    store(),
                    item["id"],
                    model=model,
                    timeout_seconds=timeout,
                )
            )
        console.print_json(data={"ok": all(row["ok"] for row in rows), "providers": rows})
