"""Provider UX command registrations."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

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
    ) -> None:
        """Run a tiny live tool-use smoke test against one provider."""
        from magent.agent import AgentSession
        from magent.ask_audit import audit_one_shot_task
        from magent.cli.command_context import build_extraction_provider, build_provider
        from magent.config import get_current_user, load_config

        username = get_current_user()
        config = load_config(username)
        root_ctx = (
            tempfile.TemporaryDirectory(prefix="magent-provider-smoke-")
            if project is None
            else None
        )
        root = Path(project or root_ctx.name).resolve()  # type: ignore[union-attr]
        root.mkdir(parents=True, exist_ok=True)
        prompt = "Use write_file to create smoke.txt containing exactly OK. Do not run shell commands."
        session = AgentSession(
            username=username,
            config=config,
            provider=build_provider(config, provider_id, model),
            extraction_provider=build_extraction_provider(config),
            cwd=str(root),
            interactive_permissions=False,
            permission_mode_override="yolo",
        )

        async def _run() -> str:
            try:
                return await session.chat(prompt)
            finally:
                await session.end_session()

        try:
            response = asyncio.run(_run())
            smoke_path = root / "smoke.txt"
            content = smoke_path.read_text(encoding="utf-8").strip() if smoke_path.exists() else ""
            audit = audit_one_shot_task(prompt, root, session.scratchpad)
            ok = content == "OK" and audit["ok"]
            provider_config = config.provider_config(provider_id)
            configured_model = (
                provider_config.get("model")
                if isinstance(provider_config, dict)
                else provider_config.model
            )
            console.print_json(
                data={
                    "ok": ok,
                    "provider": provider_id,
                    "model": model or configured_model or config.default_model,
                    "project": str(root),
                    "artifact": str(smoke_path),
                    "artifact_ok": content == "OK",
                    "audit": audit,
                    "response_preview": response[:500],
                }
            )
            if not ok:
                raise typer.Exit(1)
        finally:
            if root_ctx is not None:
                root_ctx.cleanup()
