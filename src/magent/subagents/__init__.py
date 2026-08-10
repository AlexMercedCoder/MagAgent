"""Sub-agent spawner for MagAgent.

Allows the main agent to spin up isolated child agents for parallel tasks.
Each sub-agent gets its own tool executor and conversation, but shares
the parent's memory graph (read-only by default).
"""

from __future__ import annotations

import asyncio
import contextlib
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
        quiet: bool = False,
        parent_task_id: str = "",
    ):
        self.username = username
        self.provider = provider
        self.extraction_provider = extraction_provider
        self.cwd = cwd
        self.config = config
        self.quiet = quiet
        self.parent_task_id = parent_task_id
        self._execution_task_id = ""
        self._tasks: dict[str, SubAgentTask] = {}

    async def spawn(
        self, task_id: str, description: str, *, execution_task_id: str = ""
    ) -> SubAgentTask:
        """
        Spawn a sub-agent to complete a focused task.
        Returns a SubAgentTask that gets populated as the agent runs.
        """
        execution_task_id = execution_task_id or self._execution_task_id
        self._execution_task_id = ""
        task = SubAgentTask(task_id=task_id, description=description)
        max_subagents = int(getattr(self.config, "max_subagents", 3))
        # The cap is on *concurrency*, not on how many sub-agents this runner
        # has ever spawned. Counting finished tasks meant `/spawn` failed
        # forever after N total spawns, and because goal_orchestrator reuses one
        # runner for every step, step 4 of any orchestrated goal always failed
        # under the default max of 3.
        running = sum(1 for existing in self._tasks.values() if not existing.done)
        if max_subagents <= 0 or running >= max_subagents:
            task.done = True
            task.error = f"Sub-agent cap reached ({max_subagents}). Run `magent subagent configure --max <n>` to change it."
            if not self.quiet:
                console.print(f"[dim red]✗ {task.error}[/dim red]")
            return task
        self._tasks[task_id] = task

        if not self.quiet:
            console.print(
                Panel(
                    f"[bold cyan]⚡ Spawning sub-agent[/bold cyan] [{task_id}]\n"
                    f"[dim]{description[:200]}[/dim]",
                    border_style="cyan",
                )
            )

        try:
            from magent.agent import AgentSession
            from magent.execution_bridge import SessionTaskBridge
            from magent.workbench_store import WorkbenchStore

            session = AgentSession(
                username=self.username,
                config=self.config,
                provider=self.provider,
                extraction_provider=self.extraction_provider,
                cwd=self.cwd,
                project_slug=None,
            )
            bridge = SessionTaskBridge(
                WorkbenchStore(self.username),
                session,
                kind="subagent",
                title=description[:500],
                project=self.cwd,
                permission_policy=str(getattr(self.config, "permission_mode", "balanced")),
                provider=self.provider,
                task_id=execution_task_id,
                parent_task_id=self.parent_task_id,
                metadata={"subagent_id": task_id},
            )

            # Single-turn sub-agent: send task, get result
            try:
                response = await session.chat(description)
                await session.end_session()
                bridge.complete({"ok": True, "response_chars": len(response)})
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await session.end_session()
                bridge.fail(exc)
                raise
            task.result = response
            task.done = True

            if not self.quiet:
                console.print(
                    f"[dim green]✓ Sub-agent [{task_id}] completed ({len(response)} chars)[/dim green]"
                )

        except Exception as e:
            task.error = str(e)
            task.done = True
            if not self.quiet:
                console.print(f"[dim red]✗ Sub-agent [{task_id}] failed: {e}[/dim red]")

        return task

    async def spawn_parallel(self, tasks: list[tuple[str, str]]) -> list[SubAgentTask]:
        """Spawn multiple sub-agents in parallel, in waves. Results keep order.

        Overflow tasks used to be dropped silently by `tasks[:max_parallel]` —
        the caller got fewer results than it asked for with no error.
        """
        max_parallel = max(1, int(getattr(self.config, "max_parallel_subagents", 2)))
        results: list[SubAgentTask] = []
        for start in range(0, len(tasks), max_parallel):
            wave = tasks[start : start + max_parallel]
            coros = [self.spawn(task_id, description) for task_id, description in wave]
            results.extend(await asyncio.gather(*coros, return_exceptions=False))
        return results

    def get_task(self, task_id: str) -> SubAgentTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[SubAgentTask]:
        return list(self._tasks.values())
