"""Agent definition command registrations."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def register_agent_commands(agent_app: typer.Typer) -> None:
    @agent_app.command("list")
    def agent_list_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """List built-in, user, project, and enabled plugin agents."""
        from magent.agent_defs import list_agents

        console.print_json(data=list_agents(project))

    @agent_app.command("show")
    def agent_show_cmd(name: str = typer.Argument(...), project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show one agent definition."""
        from magent.agent_defs import get_agent

        agent = get_agent(name, project)
        if not agent:
            console.print_json(data={"ok": False, "error": f"Agent not found: {name}"})
            raise typer.Exit(1)
        console.print_json(data={"ok": True, "agent": agent.as_dict()})

    @agent_app.command("create")
    def agent_create_cmd(
        name: str = typer.Argument(...),
        project: str = typer.Option(".", "--project", "-p"),
        description: str = typer.Option("", "--description"),
        mode: str = typer.Option("subagent", "--mode"),
        prompt: str = typer.Option("", "--prompt"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Create `.magent/agents/<name>.md`."""
        from magent.agent_defs import create_agent

        result = create_agent(project, name, description=description, mode=mode, prompt=prompt, force=force)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("run")
    def agent_run_cmd(
        name: str = typer.Argument(...),
        task: str = typer.Argument(...),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Render a manual `@agent` invocation prompt."""
        from magent.agent_defs import resolve_invocation

        result = resolve_invocation(f"@{name} {task}", project)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
