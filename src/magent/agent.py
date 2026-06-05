"""Core agent loop: orchestrates memory recall, LLM calls, tool dispatch, and memory writes."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from magent.config import Config, user_memory_dir
from magent.memory import MemoryManager
from magent.memory.extraction import extract_memories
from magent.providers import Provider
from magent.skills import SkillRegistry
from magent.tools import ToolExecutor

console = Console()

AGENT_SYSTEM_PROMPT = """You are MagAgent, an expert AI coding assistant with persistent memory.

You have access to tools for reading/writing files, running shell commands, searching the codebase, and fetching information from the web.

Key behaviors:
1. Always look at the user's memory context (provided below) — it tells you what you know about this user, their projects, and their preferences.
2. Use tools proactively — don't ask the user for information you can discover yourself.
3. When writing code, follow the user's established patterns and preferences from memory.
4. If you find a useful URL during research, note it explicitly so it can be bookmarked.
5. Think step-by-step for complex tasks. Break large tasks into smaller tool calls.
6. After completing a task, briefly summarize what you did.

{memory_context}
{skill_context}
"""


class AgentSession:
    """A single interactive session of MagAgent."""

    def __init__(
        self,
        username: str,
        config: Config,
        provider: Provider,
        extraction_provider: Provider,
        cwd: str,
        project_slug: str | None = None,
    ):
        self.username = username
        self.config = config
        self.provider = provider
        self.extraction_provider = extraction_provider
        self.cwd = cwd
        self.project_slug = project_slug or self._detect_project_slug(cwd)

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.turn_count = 0
        self.conversation: list[dict[str, str]] = []

        # Initialize subsystems
        memory_dir = user_memory_dir(username)
        self.memory = MemoryManager(memory_dir, config.memory_budget_tokens)
        self.tools = ToolExecutor(
            cwd=cwd,
            permission_mode=config.permission_mode,
            allowed_shell_patterns=config.allowed_shell_patterns,
            show_tool_calls=config.get("ui", "show_tool_calls", default=True),
        )

        # Load skills
        project_skills_dir = Path(cwd) / ".magent" / "skills"
        self.skill_registry = SkillRegistry(
            extra_dirs=[project_skills_dir] if project_skills_dir.exists() else None
        )
        n_skills = self.skill_registry.load()
        if n_skills:
            console.print(f"[dim]📚 Loaded {n_skills} skills[/dim]")

    def _detect_project_slug(self, cwd: str) -> str | None:
        """Infer a project slug from the directory name."""
        name = Path(cwd).name
        slug = name.lower().replace(" ", "_").replace("-", "_")
        return slug[:40] if slug else None

    def _build_system_prompt(self, user_message: str) -> str:
        """Build the system prompt with memory + skill context injected."""
        memory_context = ""
        if self.memory.available:
            recalled = self.memory.recall(user_message)
            if recalled:
                memory_context = (
                    "## Your Memory (what you know about this user)\n\n"
                    f"{recalled}\n"
                )

        skill_context = self.skill_registry.build_skill_context(user_message)

        return AGENT_SYSTEM_PROMPT.format(
            memory_context=memory_context,
            skill_context=skill_context,
        )

    async def _run_tool_loop(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Run the LLM + tool loop until the model returns a final text response.
        Returns (final_text, updated_messages).
        """
        tool_defs = self.tools.get_tool_definitions()

        while True:
            try:
                import litellm
                litellm.suppress_debug_info = True

                response = await litellm.acompletion(
                    messages=messages,
                    tools=tool_defs,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=4096,
                    **self.provider._base_kwargs,
                )
            except Exception as e:
                return f"[Provider error: {e}]", messages

            choice = response.choices[0]
            message = choice.message

            # No tool calls — this is the final response
            if not message.tool_calls:
                content = message.content or ""
                messages.append({"role": "assistant", "content": content})
                return content, messages

            # Process tool calls
            messages.append(message.model_dump())

            for tc in message.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                result = await self.tools.dispatch(tool_name, tool_args)
                result_str = json.dumps(result, indent=2, default=str)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

    async def _maybe_write_memories(self) -> None:
        """Trigger memory extraction and write if it's time."""
        if not self.config.auto_write or not self.memory.available:
            return
        if not self.conversation:
            return

        try:
            extracted = await extract_memories(
                self.conversation,
                self.extraction_provider.as_extract_fn(),
            )
            if extracted:
                n = self.memory.write_memories(extracted, self.project_slug)
                if n and self.config.get("ui", "show_memory_writes", default=False):
                    console.print(f"[dim green]💾 Wrote {n} memory nodes[/dim green]")
        except Exception as e:
            console.print(f"[dim red]Memory write error: {e}[/dim red]")

    async def chat(self, user_message: str) -> str:
        """Process one user turn. Returns the agent's response."""
        self.turn_count += 1

        # Build system prompt with fresh memory/skill context
        system_prompt = self._build_system_prompt(user_message)
        self.conversation.append({"role": "user", "content": user_message})

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *self.conversation[:-1],  # history without current turn's system
            {"role": "user", "content": user_message},
        ]

        response, _ = await self._run_tool_loop(messages)

        self.conversation.append({"role": "assistant", "content": response})

        # Memory write every N turns
        if self.turn_count % self.config.write_every_n_turns == 0:
            await self._maybe_write_memories()

        return response

    async def end_session(self) -> None:
        """Called at session end: write memories + session summary."""
        await self._maybe_write_memories()

        if self.conversation and self.memory.available:
            # Write a brief session summary
            summary_parts = [
                f"Session {self.session_id}",
                f"Project: {self.project_slug or 'unspecified'}",
                f"Turns: {self.turn_count}",
                f"Provider: {self.provider.display_name}",
            ]
            self.memory.write_session_summary(self.session_id, "\n".join(summary_parts))
