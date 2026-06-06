"""Sub-agent spawner for MagAgent.

Allows the main agent to spin up isolated child agents for parallel tasks.
Each sub-agent gets its own tool executor and conversation, but shares
the parent's memory graph (read-only by default).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel

console = Console()


@dataclass
class SubAgentTask:
    """Represents a task delegated to a sub-agent."""

    task_id: str
    description: str
    result: str = ""
    done: bool = False
    error: str = ""


class SubAgentRunner:
    """Spawns and manages sub-agents for parallel tasks."""

    def __init__(
        self,
        username: str,
        provider,
        extraction_provider,
        cwd: str,
        config,
    ):
        self.username = username
        self.provider = provider
        self.extraction_provider = extraction_provider
        self.cwd = cwd
        self.config = config
        self._tasks: dict[str, SubAgentTask] = {}

    async def spawn(self, task_id: str, description: str) -> SubAgentTask:
        """
        Spawn a sub-agent to complete a focused task.
        Returns a SubAgentTask that gets populated as the agent runs.
        """
        task = SubAgentTask(task_id=task_id, description=description)
        max_subagents = int(getattr(self.config, "max_subagents", 3))
        if max_subagents <= 0 or len(self._tasks) >= max_subagents:
            task.done = True
            task.error = f"Sub-agent cap reached ({max_subagents}). Run `magent subagent configure --max <n>` to change it."
            console.print(f"[dim red]✗ {task.error}[/dim red]")
            return task
        self._tasks[task_id] = task

        console.print(
            Panel(
                f"[bold cyan]⚡ Spawning sub-agent[/bold cyan] [{task_id}]\n"
                f"[dim]{description[:200]}[/dim]",
                border_style="cyan",
            )
        )

        try:
            from magent.agent import AgentSession

            session = AgentSession(
                username=self.username,
                config=self.config,
                provider=self.provider,
                extraction_provider=self.extraction_provider,
                cwd=self.cwd,
                project_slug=None,
            )

            # Single-turn sub-agent: send task, get result
            response = await session.chat(description)
            task.result = response
            task.done = True

            console.print(
                f"[dim green]✓ Sub-agent [{task_id}] completed ({len(response)} chars)[/dim green]"
            )

        except Exception as e:
            task.error = str(e)
            task.done = True
            console.print(f"[dim red]✗ Sub-agent [{task_id}] failed: {e}[/dim red]")

        return task

    async def spawn_parallel(self, tasks: list[tuple[str, str]]) -> list[SubAgentTask]:
        """Spawn multiple sub-agents in parallel. Returns results in order."""
        max_parallel = max(1, int(getattr(self.config, "max_parallel_subagents", 2)))
        coros = [self.spawn(tid, desc) for tid, desc in tasks[:max_parallel]]
        return list(await asyncio.gather(*coros, return_exceptions=False))

    def get_task(self, task_id: str) -> SubAgentTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[SubAgentTask]:
        return list(self._tasks.values())
