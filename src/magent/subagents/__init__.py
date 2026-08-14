"""Sub-agent spawner for MagAgent.

Allows the main agent to spin up isolated child agents for parallel tasks.
Each sub-agent gets its own tool executor and conversation, but shares
the parent's memory graph (read-only by default).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

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
        parent_profile: Any | None = None,
    ):
        self.username = username
        self.provider = provider
        self.extraction_provider = extraction_provider
        self.cwd = cwd
        self.config = config
        self.quiet = quiet
        self.parent_task_id = parent_task_id
        self.parent_profile = parent_profile
        self._execution_task_id = ""
        self._tasks: dict[str, SubAgentTask] = {}

    async def spawn(
        self,
        task_id: str,
        description: str,
        *,
        execution_task_id: str = "",
        profile_name: str = "",
    ) -> SubAgentTask:
        """
        Spawn a sub-agent to complete a focused task.
        Returns a SubAgentTask that gets populated as the agent runs.
        """
        execution_task_id = execution_task_id or self._execution_task_id
        self._execution_task_id = ""
        task = SubAgentTask(task_id=task_id, description=description)
        max_subagents = int(getattr(self.config, "max_subagents", 3))
        if self.parent_profile is not None:
            max_subagents = min(max_subagents, self.parent_profile.max_subagents)
            if self.parent_profile.max_parallel_subagents <= 0:
                task.done = True
                task.error = "Active agent profile does not permit parallel subagents"
                self._tasks[task_id] = task
                return task
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

        child_profile = None
        if self.parent_profile is not None:
            allowed = self.parent_profile.subagents
            if allowed == ():
                task.done = True
                task.error = "Active agent profile does not permit subagents"
                return task
            if self.parent_profile.max_delegation_depth <= 0:
                task.done = True
                task.error = "Agent profile delegation depth exhausted"
                return task
            if not profile_name and allowed:
                profile_name = allowed[0]
            elif not profile_name:
                # Re-resolving the parent as a child applies the delegation
                # depth decrement and preserves every parent capability ceiling.
                profile_name = self.parent_profile.name
            if profile_name and allowed is not None and profile_name not in allowed:
                task.done = True
                task.error = (
                    f"Subagent profile {profile_name!r} is outside the parent delegation policy"
                )
                return task
        if profile_name:
            from magent.agent_profiles.effective import resolve_effective_profile
            from magent.agent_profiles.registry import AgentProfileRegistry
            from magent.tools.catalog import built_in_tool_definitions

            resolved = AgentProfileRegistry(self.cwd, self.config).get(profile_name)
            if resolved is None:
                task.done = True
                task.error = f"Subagent profile not found: {profile_name}"
                return task
            granted = {
                item.get("function", {}).get("name", "") for item in built_in_tool_definitions()
            }
            child_profile = resolve_effective_profile(
                resolved,
                self.config,
                granted,
                parent=self.parent_profile,
            )

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

            child_provider = self.provider
            if child_profile is not None and (
                child_profile.provider != getattr(self.provider, "provider_id", "")
                or child_profile.model != getattr(self.provider, "model", "")
            ):
                from magent.providers import build_provider

                provider_config = self.config.provider_config(child_profile.provider)
                provider_credential = self.config.resolve_api_key(
                    child_profile.provider
                ) or provider_config.get("api_key")
                child_provider = build_provider(
                    child_profile.provider,
                    child_profile.model,
                    provider_credential,
                    provider_config,
                )
            session = AgentSession(
                username=self.username,
                config=self.config,
                provider=child_provider,
                extraction_provider=self.extraction_provider,
                cwd=self.cwd,
                project_slug=None,
                profile=child_profile,
            )
            bridge = SessionTaskBridge(
                WorkbenchStore(self.username),
                session,
                kind="subagent",
                title=description[:500],
                project=self.cwd,
                permission_policy=str(getattr(self.config, "permission_mode", "balanced")),
                provider=child_provider,
                task_id=execution_task_id,
                parent_task_id=self.parent_task_id,
                metadata={
                    "subagent_id": task_id,
                    "agent_profile": child_profile.name if child_profile else "",
                    "parent_agent_profile": (
                        self.parent_profile.name if self.parent_profile else ""
                    ),
                },
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
        if self.parent_profile is not None:
            max_parallel = max(1, min(max_parallel, self.parent_profile.max_parallel_subagents))
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
