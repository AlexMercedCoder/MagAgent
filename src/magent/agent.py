"""Core agent loop: orchestrates memory recall, LLM calls, tool dispatch, and memory writes."""

from __future__ import annotations

import asyncio
import html
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from magent.agent_defs import resolve_invocation
from magent.cache import extract_cache_usage
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

AGENT_STATIC_PROMPT = """You are MagAgent, an expert AI coding assistant with persistent memory.

You have access to tools for reading/writing files, running shell commands, searching the codebase, and fetching information from the web.
You also have access to MCP (Model Context Protocol) tools from connected servers — these appear as mcp__<server>__<tool_name>.

Key behaviors:
1. Always look at the user's memory context when provided — it tells you what you know about this user, their projects, and their preferences.
2. Use tools proactively — don't ask the user for information you can discover yourself.
3. When writing code, follow the user's established patterns and preferences from memory.
4. If you find a useful URL during research, note it explicitly so it can be bookmarked.
5. Think step-by-step for complex tasks. Break large tasks into smaller tool calls.
6. After completing a task, briefly summarize what you did.
7. For file reads over 100 lines, prefer outline_file first, then read only the relevant range.
8. Prefer narrow edit_file changes over whole-file rewrites whenever possible.
9. Tool outputs may be compressed; use targeted follow-up tools for exact ranges or full details.
10. Prefer native tools over shell probes: use read_file/list_dir for file checks, write_file/edit_file for file changes, and install_package for Python packages.
11. If the user denies a permission request, stop trying equivalent commands and explain the blocked action briefly.
12. On macOS, prefer python3/pip3 or python3 -m pip; avoid bare python/pip commands.
13. During research, prefer web_fetch/http_request over repeated curl shell probes. If shell inspection is necessary, use one broad read-only fetch pipeline instead of many tiny variations.
14. Never use run_shell, heredocs, redirection, tee, or Python snippets to create or edit files. For any generated file, call write_file with the full final content; for changes, call edit_file.
"""

AGENT_CONTEXT_PROMPT = """The following context changes by project and turn. Use it as relevant, but do not repeat it unless needed.

{memory_context}
{repo_context}
{session_context}
{skill_context}
"""

AGENT_SYSTEM_PROMPT = AGENT_STATIC_PROMPT + "\n\n" + AGENT_CONTEXT_PROMPT


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
        interactive_permissions: bool = True,
        permission_mode_override: str | None = None,
    ):
        self.username = username
        self.config = config
        self.provider = provider
        self.extraction_provider = extraction_provider
        self.cwd = cwd
        self.project_slug = project_slug or self._detect_project_slug(cwd)
        permission_mode = permission_mode_override or config.permission_mode

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
        self.turn_count = 0
        self.conversation: list[dict[str, str]] = []
        self.compacted_summary = ""
        self.scratchpad: dict[str, Any] = {
            "project": self.project_slug,
            "files_touched": [],
            "commands_run": [],
            "decisions": [],
            "permission_failures": [],
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
            permission_mode=permission_mode,
            allowed_shell_patterns=config.allowed_shell_patterns,
            trusted_shell_patterns=config.trusted_shell_patterns,
            show_tool_calls=config.get("ui", "show_tool_calls", default=True),
            username=username,
            tool_budgets=config.get("tool_budgets", default={}),
            session_id=self.session_id,
            interactive_permissions=interactive_permissions,
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
        return self._build_stable_prompt() + "\n\n" + self._build_context_prompt(user_message)

    def _build_stable_prompt(self) -> str:
        return AGENT_STATIC_PROMPT

    def _build_context_prompt(self, user_message: str) -> str:
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
        return AGENT_CONTEXT_PROMPT.format(
            memory_context=memory_context,
            repo_context=repo_context,
            session_context=session_context,
            skill_context=skill_context,
        )

    def _build_prompt_messages(self, user_message: str) -> list[dict[str, Any]]:
        context_prompt = self._build_context_prompt(user_message)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._build_stable_prompt()}]
        if context_prompt.strip():
            messages.append({"role": "system", "content": context_prompt})
        messages.extend(self._conversation_messages_for_prompt())
        messages.append({"role": "user", "content": user_message})
        return messages

    def _provider_request_kwargs(self) -> dict[str, Any]:
        if hasattr(self.provider, "request_kwargs"):
            return self.provider.request_kwargs(
                self.config,
                username=self.username,
                project_slug=self.project_slug,
                session_id=self.session_id,
                cwd=self.cwd,
            )
        return dict(getattr(self.provider, "_base_kwargs", {}))

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
        pseudo_retry_count = 0

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
                    **self._provider_request_kwargs(),
                )
                self._log_llm_usage(response)
            except Exception as e:
                return f"[Provider error: {e}]", messages, total_tool_calls

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                content = message.content or ""
                pseudo_calls = _extract_pseudo_tool_calls(content)
                if pseudo_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": _strip_pseudo_tool_markup(content) or "Using tools.",
                        }
                    )
                    total_tool_calls += len(pseudo_calls)
                    for tool_name, tool_args in pseudo_calls:
                        result = await self._dispatch_tool_call(tool_name, tool_args)
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    f"Parsed and executed assistant-emitted tool markup for `{tool_name}`. "
                                    f"Tool result:\n{self._compress_tool_result(tool_name, result)}"
                                ),
                            }
                        )
                        if self._permission_denied_by_user(result):
                            content = self._permission_denial_summary(tool_name, tool_args)
                            messages.append({"role": "assistant", "content": content})
                            return content, messages, total_tool_calls
                        if self.config.prune_stale_tool_results:
                            self._prune_stale_tool_results(messages, tool_name, result)
                    continue
                if _contains_pseudo_tool_markup(content):
                    pseudo_retry_count += 1
                    if pseudo_retry_count > 2:
                        content = (
                            "I tried to use a tool, but the provider returned truncated tool markup. "
                            "Please retry the request; I will use native file tools instead of printing the file."
                        )
                        messages.append({"role": "assistant", "content": content})
                        return content, messages, total_tool_calls
                    messages.append(
                        {
                            "role": "assistant",
                            "content": _strip_pseudo_tool_markup(content) or "Tool markup was incomplete.",
                        }
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The previous assistant response contained incomplete DSML tool markup and was not executed. "
                                "Retry by using the native tool call API, especially write_file for generated files. "
                                "Do not print DSML or the full file content as normal assistant text."
                            ),
                        }
                    )
                    continue
                if not content.strip() and total_tool_calls:
                    content = self._fallback_tool_summary()
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
                if self._permission_denied_by_user(result):
                    content = self._permission_denial_summary(tool_name, tool_args)
                    messages.append({"role": "assistant", "content": content})
                    return content, messages, total_tool_calls
                if self.config.prune_stale_tool_results:
                    self._prune_stale_tool_results(messages, tool_name, result)

        return "", messages, total_tool_calls  # unreachable

    async def stream_chat(self, user_message: str) -> AsyncIterator[str]:
        """Stream the agent response token by token. Yields text chunks."""
        user_message = self._resolve_agent_message(user_message)
        self.turn_count += 1
        self.logger.log_user_turn(self.turn_count, user_message)
        self.conversation.append({"role": "user", "content": user_message})

        messages = self._build_prompt_messages(user_message)

        # Run tool loop first (tools don't stream)
        # Wait for MCP servers to finish connecting (if still starting)
        if self._mcp_start_task and not self._mcp_start_task.done():
            await self._mcp_start_task

        # Merge built-in tools + MCP tools
        tool_defs = self._tool_definitions(user_message)
        total_tool_calls = 0
        pseudo_retry_count = 0

        try:
            import litellm

            litellm.suppress_debug_info = True

            # First pass: tool loop
            console.print("[dim]thinking...[/dim]")
            while True:
                response = await litellm.acompletion(
                    messages=_sanitize_messages(messages),
                    tools=tool_defs,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=4096,
                    **self._provider_request_kwargs(),
                )
                self._log_llm_usage(response)
                choice = response.choices[0]
                msg = choice.message

                if not msg.tool_calls:
                    # Got final text. Do not make a second "finalizing" model call:
                    # some OpenAI-compatible models emit pseudo tool-call markup when
                    # tools are removed, which can claim work happened without running it.
                    content = msg.content or ""
                    pseudo_calls = _extract_pseudo_tool_calls(content)
                    if pseudo_calls:
                        messages.append(
                            {
                                "role": "assistant",
                                "content": _strip_pseudo_tool_markup(content) or "Using tools.",
                            }
                        )
                        total_tool_calls += len(pseudo_calls)
                        for tool_name, tool_args in pseudo_calls:
                            result = await self._dispatch_tool_call(tool_name, tool_args)
                            messages.append(
                                {
                                    "role": "system",
                                    "content": (
                                        f"Parsed and executed assistant-emitted tool markup for `{tool_name}`. "
                                        f"Tool result:\n{self._compress_tool_result(tool_name, result)}"
                                    ),
                                }
                            )
                            if self._permission_denied_by_user(result):
                                full_response = self._permission_denial_summary(tool_name, tool_args)
                                messages.append({"role": "assistant", "content": full_response})
                                self.conversation.append({"role": "assistant", "content": full_response})
                                self.logger.log_assistant_turn(
                                    self.turn_count,
                                    full_response,
                                    total_tool_calls,
                                )
                                yield full_response
                                self._maybe_compact_conversation()
                                return
                            if self.config.prune_stale_tool_results:
                                self._prune_stale_tool_results(messages, tool_name, result)
                        continue
                    if _contains_pseudo_tool_markup(content):
                        pseudo_retry_count += 1
                        if pseudo_retry_count > 2:
                            full_response = (
                                "I tried to use a tool, but the provider returned truncated tool markup. "
                                "Please retry the request; I will use native file tools instead of printing the file."
                            )
                            messages.append({"role": "assistant", "content": full_response})
                            self.conversation.append({"role": "assistant", "content": full_response})
                            self.logger.log_assistant_turn(self.turn_count, full_response, total_tool_calls)
                            yield full_response
                            self._maybe_compact_conversation()
                            return
                        messages.append(
                            {
                                "role": "assistant",
                                "content": _strip_pseudo_tool_markup(content) or "Tool markup was incomplete.",
                            }
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "The previous assistant response contained incomplete DSML tool markup and was not executed. "
                                    "Retry by using the native tool call API, especially write_file for generated files. "
                                    "Do not print DSML or the full file content as normal assistant text."
                                ),
                            }
                        )
                        continue
                    if not (msg.content or "").strip() and total_tool_calls:
                        fallback = self._fallback_tool_summary()
                        messages.append({"role": "assistant", "content": fallback})
                        self.conversation.append({"role": "assistant", "content": fallback})
                        self.logger.log_assistant_turn(self.turn_count, fallback, total_tool_calls)
                        yield fallback
                        if self.turn_count % self.config.write_every_n_turns == 0:
                            await self._maybe_write_memories()
                        self._maybe_compact_conversation()
                        return
                    full_response = content
                    messages.append(_sanitize_message(msg.model_dump()))
                    self.conversation.append({"role": "assistant", "content": full_response})
                    self.logger.log_assistant_turn(self.turn_count, full_response, total_tool_calls)
                    yield full_response
                    if self.turn_count % self.config.write_every_n_turns == 0:
                        await self._maybe_write_memories()
                    self._maybe_compact_conversation()
                    return

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
                    if self._permission_denied_by_user(result):
                        full_response = self._permission_denial_summary(tool_name, tool_args)
                        messages.append({"role": "assistant", "content": full_response})
                        self.conversation.append({"role": "assistant", "content": full_response})
                        self.logger.log_assistant_turn(
                            self.turn_count,
                            full_response,
                            total_tool_calls,
                        )
                        yield full_response
                        self._maybe_compact_conversation()
                        return
                    if self.config.prune_stale_tool_results:
                        self._prune_stale_tool_results(messages, tool_name, result)

        except Exception as e:
            err = f"\n[Error: {e}]"
            yield err

    async def chat(self, user_message: str) -> str:
        """Non-streaming completion. Returns full response string."""
        user_message = self._resolve_agent_message(user_message)
        self.turn_count += 1
        self.logger.log_user_turn(self.turn_count, user_message)
        self.conversation.append({"role": "user", "content": user_message})

        messages = self._build_prompt_messages(user_message)

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

    def _fallback_tool_summary(self) -> str:
        """Return a useful completion message when a provider returns empty text."""
        files = self.scratchpad.get("files_touched") or []
        commands = self.scratchpad.get("commands_run") or []
        parts = ["Done."]
        if files:
            parts.append("Files touched: " + ", ".join(str(path) for path in files[-5:]) + ".")
        if commands:
            parts.append("Commands run: " + "; ".join(str(cmd) for cmd in commands[-3:]) + ".")
        return " ".join(parts)

    def _permission_denied_by_user(self, result: dict[str, Any]) -> bool:
        return (
            result.get("ok") is False
            and result.get("permission_reason") == "user-denied"
        )

    def _permission_denial_summary(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        if tool_name == "run_shell":
            command = str(tool_args.get("command", "")).strip()
            return (
                "Stopped because you denied the shell command"
                + (f": `{command}`." if command else ".")
                + " I will not retry equivalent shell probes unless you ask me to."
            )
        return (
            f"Stopped because you denied permission for `{tool_name}`. "
            "I will not retry equivalent actions unless you ask me to."
        )

    async def _dispatch_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call and record hooks, scratchpad, and audit logs."""
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

        from magent.permissions import RiskTier, classify_shell_command

        tier = RiskTier.AUTO
        if tool_name == "run_shell":
            tier = classify_shell_command(
                tool_args.get("command", ""),
                self.config.allowed_shell_patterns,
            )
        self.logger.log_tool_call(tool_name, tool_args, result.get("ok", True), int(tier))
        return result

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
        if result.get("permission_required"):
            self._remember_scratchpad(
                "permission_failures",
                f"{tool_name}: {result.get('error', 'permission required')}",
            )

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
        cache_usage = extract_cache_usage(usage)
        cached_tokens = int(cache_usage["cached_tokens"] or 0)
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
            cache_hit_tokens=int(cache_usage["cache_hit_tokens"] or 0),
            cache_miss_tokens=int(cache_usage["cache_miss_tokens"] or 0),
            cache_write_tokens=int(cache_usage["cache_write_tokens"] or 0),
            cache_source=str(cache_usage["cache_source"] or ""),
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


_DSML = r"[|｜]+DSML[|｜]+"
_DSML_INVOKE_RE = re.compile(
    rf"<{_DSML}invoke\s+name=[\"']([^\"']+)[\"']\s*>(.*?)(?=<{_DSML}invoke\s+name=|</?{_DSML}tool_calls|$)",
    re.DOTALL,
)
_DSML_PARAMETER_RE = re.compile(
    rf"<{_DSML}parameter\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)</{_DSML}parameter>",
    re.DOTALL,
)
_DSML_START_RE = re.compile(rf"<{_DSML}(tool_calls|invoke|parameter)\b", re.DOTALL)


def _contains_pseudo_tool_markup(content: str) -> bool:
    """Return true when a provider printed DSML tool markup as text."""
    return bool(_DSML_START_RE.search(content or ""))


def _extract_pseudo_tool_calls(content: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse DSML-style pseudo tool calls emitted as text by some providers."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for match in _DSML_INVOKE_RE.finditer(content or ""):
        tool_name = match.group(1).strip()
        body = match.group(2)
        args: dict[str, Any] = {}
        for param in _DSML_PARAMETER_RE.finditer(body):
            key = param.group(1).strip()
            value = html.unescape(param.group(2))
            args[key] = value
        if tool_name and args:
            calls.append((tool_name, args))
    return calls


def _strip_pseudo_tool_markup(content: str) -> str:
    """Keep any explanatory text before pseudo tool markup and discard the markup."""
    match = _DSML_START_RE.search(content or "")
    if not match:
        return content
    return content[: match.start()].strip()


def reflow(text: str) -> str:
    """Collapse whitespace for compact session summaries."""
    return " ".join((text or "").split())
