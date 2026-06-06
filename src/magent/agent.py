"""Core agent loop: orchestrates memory recall, LLM calls, tool dispatch, and memory writes."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from magent.agent_defs import resolve_invocation
from magent.config import Config, user_memory_dir
from magent.hooks import run_hooks
from magent.logging import SessionLogger
from magent.memory import MemoryManager
from magent.memory.extraction import extract_memories
from magent.providers import Provider
from magent.repo_map import RepoMapCache
from magent.skills import SkillRegistry
from magent.tokens import estimate_tokens, truncate_to_tokens
from magent.tools import ToolExecutor

console = Console()

STRIP_MESSAGE_KEYS = {"provider_specific_fields"}

AGENT_SYSTEM_PROMPT = """You are MagAgent, an expert AI coding assistant with persistent memory.

You have access to tools for reading/writing files, running shell commands, searching the codebase, and fetching information from the web.
You also have access to MCP (Model Context Protocol) tools from connected servers — these appear as mcp__<server>__<tool_name>.

Key behaviors:
1. Always look at the user's memory context (provided below) — it tells you what you know about this user, their projects, and their preferences.
2. Use tools proactively — don't ask the user for information you can discover yourself.
3. When writing code, follow the user's established patterns and preferences from memory.
4. If you find a useful URL during research, note it explicitly so it can be bookmarked.
5. Think step-by-step for complex tasks. Break large tasks into smaller tool calls.
6. After completing a task, briefly summarize what you did.
7. For file reads over 100 lines, prefer outline_file first, then read only the relevant range.
8. Prefer narrow edit_file changes over whole-file rewrites whenever possible.
9. Tool outputs may be compressed; use targeted follow-up tools for exact ranges or full details.

{memory_context}
{repo_context}
{session_context}
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

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        self.turn_count = 0
        self.conversation: list[dict[str, str]] = []
        self.compacted_summary = ""
        self.scratchpad: dict[str, Any] = {
            "project": self.project_slug,
            "files_touched": [],
            "commands_run": [],
            "decisions": [],
        }

        # Initialize subsystems
        memory_dir = user_memory_dir(username)
        self.memory = MemoryManager(
            memory_dir,
            config.memory_budget_tokens,
            max_node_tokens=config.recall_body_tokens,
            username=username,
            semantic_enabled=config.semantic_memory_enabled,
            semantic_provider=config.semantic_memory_provider,
            semantic_model=config.semantic_memory_model,
        )
        self.repo_map = RepoMapCache(cwd)
        self.tools = ToolExecutor(
            cwd=cwd,
            permission_mode=config.permission_mode,
            allowed_shell_patterns=config.allowed_shell_patterns,
            show_tool_calls=config.get("ui", "show_tool_calls", default=True),
            username=username,
            tool_budgets=config.get("tool_budgets", default={}),
            session_id=self.session_id,
        )

        # MCP servers (optional — connect only if configured)
        from magent.mcp import MCPManager

        mcp_servers_cfg = config.get("mcp", "servers", default={})
        self.mcp = MCPManager(mcp_servers_cfg if isinstance(mcp_servers_cfg, dict) else {})
        # Start MCP connections in the background (don't block __init__)
        self._mcp_start_task: asyncio.Task[Any] | None = None
        if mcp_servers_cfg:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._mcp_start_task = loop.create_task(self.mcp.start_all())

        # Load skills
        project_skills_dir = Path(cwd) / ".magent" / "skills"
        self.skill_registry = SkillRegistry(
            extra_dirs=[project_skills_dir] if project_skills_dir.exists() else None
        )
        n_skills = self.skill_registry.load()
        if n_skills:
            console.print(f"[dim]📚 Loaded {n_skills} skills[/dim]")

        # Session logger
        self.logger = SessionLogger(self.session_id, username)
        self.logger.log_session_start(provider.provider_id, provider.model, cwd)

        # Sub-agent runner (lazy init)
        self._subagent_runner = None

    def _detect_project_slug(self, cwd: str) -> str | None:
        name = Path(cwd).name
        slug = name.lower().replace(" ", "_").replace("-", "_")
        return slug[:40] if slug else None

    def _cwd(self) -> str:
        return str(getattr(self, "cwd", "."))

    def _build_system_prompt(self, user_message: str) -> str:
        memory_context = ""
        if self.memory.available:
            recalled = self.memory.recall(user_message)
            if recalled:
                memory_context = f"## Your Memory (what you know about this user)\n\n{recalled}\n"
        repo_context = ""
        repo_slice = self.repo_map.relevant_slice(user_message, self.config.repo_map_budget_tokens)
        if repo_slice:
            repo_context = f"{repo_slice}\n"
        session_context = self._build_session_context()
        skill_context = self.skill_registry.build_skill_context(
            user_message,
            budget_tokens=self.config.skill_budget_tokens,
        )
        return AGENT_SYSTEM_PROMPT.format(
            memory_context=memory_context,
            repo_context=repo_context,
            session_context=session_context,
            skill_context=skill_context,
        )

    def _build_session_context(self) -> str:
        parts = ["## Session State", ""]
        if self.compacted_summary:
            parts.extend(["### Compacted Conversation", self.compacted_summary, ""])
        files = self.scratchpad.get("files_touched") or []
        commands = self.scratchpad.get("commands_run") or []
        if files:
            parts.append("Files touched: " + ", ".join(f"`{f}`" for f in files[-12:]))
        if commands:
            parts.append("Recent commands: " + "; ".join(f"`{c}`" for c in commands[-8:]))
        if len(parts) <= 2:
            return ""
        return "\n".join(parts) + "\n"

    def _conversation_messages_for_prompt(self) -> list[dict[str, str]]:
        if not self.compacted_summary:
            return self.conversation[:-1]
        keep = self.config.keep_recent_turns
        return self.conversation[-(keep + 1) : -1] if keep > 0 else []

    async def _run_tool_loop(
        self, messages: list[dict[str, Any]], user_message: str = ""
    ) -> tuple[str, list[dict[str, Any]], int]:
        """
        Run the LLM + tool loop. Returns (final_text, updated_messages, tool_call_count).
        """
        # Wait for MCP servers to finish connecting (if still starting)
        if self._mcp_start_task and not self._mcp_start_task.done():
            await self._mcp_start_task

        # Merge built-in tools + MCP tools
        tool_defs = self._tool_definitions(user_message)
        total_tool_calls = 0

        while True:
            try:
                import litellm

                litellm.suppress_debug_info = True

                response = await litellm.acompletion(
                    messages=_sanitize_messages(messages),
                    tools=tool_defs,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=4096,
                    **self.provider._base_kwargs,
                )
                self._log_llm_usage(response)
            except Exception as e:
                return f"[Provider error: {e}]", messages, total_tool_calls

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                content = message.content or ""
                messages.append({"role": "assistant", "content": content})
                return content, messages, total_tool_calls

            messages.append(_sanitize_message(message.model_dump()))
            total_tool_calls += len(message.tool_calls)

            for tc in message.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                # Route to MCP or built-in tool
                run_hooks(self._cwd(), "pre_tool", {"tool": tool_name, "args": tool_args})
                if self.mcp.is_mcp_tool(tool_name):
                    result = await self.mcp.dispatch(tool_name, tool_args)
                else:
                    result = await self.tools.dispatch(tool_name, tool_args)
                run_hooks(self._cwd(), "post_tool", {"tool": tool_name, "args": tool_args, "result": result})
                if tool_name in {"write_file", "edit_file", "delete_file"}:
                    run_hooks(self._cwd(), "post_edit", {"tool": tool_name, "args": tool_args, "result": result})
                if tool_name == "run_shell" and not result.get("ok", True):
                    run_hooks(self._cwd(), "command_failure", {"tool": tool_name, "args": tool_args, "result": result})
                self._observe_tool_result(tool_name, tool_args, result)
                result_str = self._compress_tool_result(tool_name, result)

                # Log the tool call
                from magent.permissions import RiskTier, classify_shell_command

                tier = RiskTier.AUTO
                if tool_name == "run_shell":
                    tier = classify_shell_command(
                        tool_args.get("command", ""),
                        self.config.allowed_shell_patterns,
                    )
                self.logger.log_tool_call(tool_name, tool_args, result.get("ok", True), int(tier))

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                        "name": tool_name,
                    }
                )
                if self.config.prune_stale_tool_results:
                    self._prune_stale_tool_results(messages, tool_name, result)

        return "", messages, total_tool_calls  # unreachable

    async def stream_chat(self, user_message: str) -> AsyncIterator[str]:
        """Stream the agent response token by token. Yields text chunks."""
        user_message = self._resolve_agent_message(user_message)
        self.turn_count += 1
        self.logger.log_user_turn(self.turn_count, user_message)
        self.conversation.append({"role": "user", "content": user_message})

        system_prompt = self._build_system_prompt(user_message)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *self._conversation_messages_for_prompt(),
        ]
        messages.append({"role": "user", "content": user_message})

        # Run tool loop first (tools don't stream)
        # Wait for MCP servers to finish connecting (if still starting)
        if self._mcp_start_task and not self._mcp_start_task.done():
            await self._mcp_start_task

        # Merge built-in tools + MCP tools
        tool_defs = self._tool_definitions(user_message)
        total_tool_calls = 0

        try:
            import litellm

            litellm.suppress_debug_info = True

            # First pass: tool loop
            while True:
                response = await litellm.acompletion(
                    messages=_sanitize_messages(messages),
                    tools=tool_defs,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=4096,
                    **self.provider._base_kwargs,
                )
                self._log_llm_usage(response)
                choice = response.choices[0]
                msg = choice.message

                if not msg.tool_calls:
                    # Got text — now stream it
                    messages.append(_sanitize_message(msg.model_dump()))
                    break

                messages.append(_sanitize_message(msg.model_dump()))
                total_tool_calls += len(msg.tool_calls)

                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    # Route to MCP or built-in tool
                    run_hooks(self._cwd(), "pre_tool", {"tool": tool_name, "args": tool_args})
                    if self.mcp.is_mcp_tool(tool_name):
                        result = await self.mcp.dispatch(tool_name, tool_args)
                    else:
                        result = await self.tools.dispatch(tool_name, tool_args)
                    run_hooks(self._cwd(), "post_tool", {"tool": tool_name, "args": tool_args, "result": result})
                    if tool_name in {"write_file", "edit_file", "delete_file"}:
                        run_hooks(self._cwd(), "post_edit", {"tool": tool_name, "args": tool_args, "result": result})
                    if tool_name == "run_shell" and not result.get("ok", True):
                        run_hooks(self._cwd(), "command_failure", {"tool": tool_name, "args": tool_args, "result": result})
                    self._observe_tool_result(tool_name, tool_args, result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": self._compress_tool_result(tool_name, result),
                            "name": tool_name,
                        }
                    )
                    if self.config.prune_stale_tool_results:
                        self._prune_stale_tool_results(messages, tool_name, result)

            # Final streaming pass — text only, no tools
            stream_response = await litellm.acompletion(
                messages=_sanitize_messages(messages),
                temperature=0.3,
                max_tokens=4096,
                stream=True,
                **self.provider._base_kwargs,
            )

            full_response = ""
            async for chunk in stream_response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_response += delta.content
                    yield delta.content

            self.conversation.append({"role": "assistant", "content": full_response})
            self.logger.log_assistant_turn(self.turn_count, full_response, total_tool_calls)
            self.logger.log_token_usage(
                provider=self.provider.provider_id,
                model=self.provider.model,
                prompt_tokens=estimate_tokens(json.dumps(messages, default=str)),
                completion_tokens=estimate_tokens(full_response),
                estimated=True,
            )

            if self.turn_count % self.config.write_every_n_turns == 0:
                await self._maybe_write_memories()
            self._maybe_compact_conversation()

        except Exception as e:
            err = f"\n[Error: {e}]"
            yield err

    async def chat(self, user_message: str) -> str:
        """Non-streaming completion. Returns full response string."""
        user_message = self._resolve_agent_message(user_message)
        self.turn_count += 1
        self.logger.log_user_turn(self.turn_count, user_message)
        self.conversation.append({"role": "user", "content": user_message})

        system_prompt = self._build_system_prompt(user_message)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *self._conversation_messages_for_prompt(),
        ]
        messages.append({"role": "user", "content": user_message})

        response, _, tool_call_count = await self._run_tool_loop(messages, user_message)
        self.conversation.append({"role": "assistant", "content": response})
        self.logger.log_assistant_turn(self.turn_count, response, tool_call_count)

        if self.turn_count % self.config.write_every_n_turns == 0:
            await self._maybe_write_memories()
        self._maybe_compact_conversation()

        return response

    def _resolve_agent_message(self, user_message: str) -> str:
        invocation = resolve_invocation(user_message, self._cwd())
        if invocation.get("ok"):
            agent = invocation.get("agent", {})
            self.scratchpad["active_agent"] = agent.get("name")
            return invocation["message"]
        return user_message

    def _maybe_compact_conversation(self) -> None:
        keep = self.config.keep_recent_turns
        if len(self.conversation) <= keep + 2:
            return
        history_tokens = estimate_tokens("\n".join(t["content"] for t in self.conversation))
        interval_hit = (
            self.config.compact_every_n_turns > 0
            and self.turn_count % self.config.compact_every_n_turns == 0
        )
        budget_hit = history_tokens > self.config.max_history_tokens
        if not interval_hit and not budget_hit:
            return

        old_turns = self.conversation[:-keep]
        self.conversation = self.conversation[-keep:]
        summary_lines = []
        if self.compacted_summary:
            summary_lines.append(self.compacted_summary)
        summary_lines.append(f"Compacted {len(old_turns)} older turns at turn {self.turn_count}.")
        for turn in old_turns[-12:]:
            role = turn.get("role", "unknown")
            content = reflow(turn.get("content", ""))
            summary_lines.append(f"- {role}: {truncate_to_tokens(content, 60, '[...]')}")
        self.compacted_summary = truncate_to_tokens("\n".join(summary_lines), 1200)
        console.print(
            f"[dim]Compacted conversation history (~{history_tokens} tokens before compaction).[/dim]"
        )

    def _observe_tool_result(
        self, tool_name: str, tool_args: dict[str, Any], result: dict[str, Any]
    ) -> None:
        if tool_name in {"write_file", "edit_file", "delete_file"} and result.get("path"):
            self._remember_scratchpad("files_touched", str(result["path"]))
        if tool_name == "run_shell":
            command = str(tool_args.get("command", ""))
            if command:
                self._remember_scratchpad("commands_run", command)

    def _remember_scratchpad(self, key: str, value: str, limit: int = 40) -> None:
        values = list(self.scratchpad.get(key) or [])
        if value not in values:
            values.append(value)
        self.scratchpad[key] = values[-limit:]

    def _compress_tool_result(self, tool_name: str, result: dict[str, Any]) -> str:
        compressed = dict(result)
        max_tokens = 1200
        if tool_name in {"read_file", "web_fetch"}:
            max_tokens = 1800
        elif tool_name in {"search_codebase", "list_dir", "system_info"}:
            max_tokens = 900

        for key in ("content", "stdout", "stderr", "body_text", "diff", "base64"):
            if isinstance(compressed.get(key), str):
                marker = f"[...{key} truncated; use targeted follow-up tools for more...]"
                compressed[key] = truncate_to_tokens(compressed[key], max_tokens, marker)

        if isinstance(compressed.get("matches"), list) and len(compressed["matches"]) > 60:
            compressed["matches"] = compressed["matches"][:60]
            compressed["truncated"] = True
        if isinstance(compressed.get("entries"), list) and len(compressed["entries"]) > 80:
            compressed["entries"] = compressed["entries"][:80]
            compressed["truncated"] = True

        text = json.dumps(compressed, indent=2, default=str)
        return truncate_to_tokens(text, max_tokens + 300, "[...tool result truncated...]")

    def _prune_stale_tool_results(
        self,
        messages: list[dict[str, Any]],
        tool_name: str,
        result: dict[str, Any],
    ) -> None:
        if tool_name not in {"write_file", "edit_file", "delete_file"} or not result.get("path"):
            return
        changed_path = str(result["path"])
        pruned = 0
        saved = 0
        for message in messages:
            if message.get("role") != "tool" or message.get("name") not in {
                "read_file",
                "read_file_range",
                "outline_file",
            }:
                continue
            content = str(message.get("content", ""))
            if changed_path not in content or content.startswith("[pruned"):
                continue
            saved += estimate_tokens(content)
            message["content"] = (
                f"[pruned stale {message.get('name')} result — "
                f"{changed_path} changed via {tool_name}]"
            )
            pruned += 1
        if pruned:
            self.logger.log_context_pruned("stale_file_tool_result", pruned, saved)

    def _tool_definitions(self, user_message: str) -> list[dict[str, Any]]:
        if self.config.selective_tools:
            builtins = self.tools.get_tool_definitions_for_message(user_message)
        else:
            builtins = self.tools.get_tool_definitions()
        return builtins + self.mcp.get_tool_definitions()

    def _log_llm_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or prompt_tokens + completion_tokens)
        cached_tokens = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details:
            cached_tokens = int(getattr(details, "cached_tokens", 0) or 0)
        if not cached_tokens and isinstance(usage, dict):
            details_dict = usage.get("prompt_tokens_details") or {}
            cached_tokens = int(details_dict.get("cached_tokens") or 0)
        cost = None
        try:
            import litellm

            cost = float(litellm.completion_cost(completion_response=response))
        except Exception:
            cost = None
        self.logger.log_token_usage(
            provider=self.provider.provider_id,
            model=self.provider.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost,
        )

    async def spawn_subagent(self, task_id: str, description: str) -> str:
        """Spawn a focused sub-agent for a parallel task. Returns its result."""
        from magent.subagents import SubAgentRunner

        if self._subagent_runner is None:
            self._subagent_runner = SubAgentRunner(
                username=self.username,
                provider=self.provider,
                extraction_provider=self.extraction_provider,
                cwd=self.cwd,
                config=self.config,
            )
        task = await self._subagent_runner.spawn(task_id, description)
        return task.result if task.done and not task.error else f"[sub-agent error: {task.error}]"

    async def _maybe_write_memories(self) -> None:
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
                self.logger.log_memory_write(n, self.project_slug)
                if n and self.config.get("ui", "show_memory_writes", default=False):
                    console.print(f"[dim green]💾 Wrote {n} memory nodes[/dim green]")
        except Exception as e:
            console.print(f"[dim red]Memory write error: {e}[/dim red]")

    async def end_session(self) -> None:
        await self._maybe_write_memories()
        if self.conversation and self.memory.available:
            summary_parts = [
                f"Session {self.session_id}",
                f"Project: {self.project_slug or 'unspecified'}",
                f"Turns: {self.turn_count}",
                f"Provider: {self.provider.display_name}",
            ]
            self.memory.write_session_summary(self.session_id, "\n".join(summary_parts))
        self.logger.log_session_end(self.turn_count)
        self.logger.close()
        # Stop all MCP server connections
        await self.mcp.stop_all()


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove SDK/provider-only fields before sending conversation history."""
    return [_sanitize_message(message) for message in messages]


def _sanitize_message(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_message(item)
            for key, item in value.items()
            if key not in STRIP_MESSAGE_KEYS and item is not None
        }
    if isinstance(value, list):
        return [_sanitize_message(item) for item in value]
    return value


def reflow(text: str) -> str:
    """Collapse whitespace for compact session summaries."""
    return " ".join((text or "").split())
