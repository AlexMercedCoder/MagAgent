"""Conversation, memory, subagent, and session lifecycle."""

from __future__ import annotations

import json
from typing import Any

from magent.agent_runtime.support import FILE_MUTATION_TOOLS, console, reflow
from magent.cache import extract_cache_usage
from magent.memory.extraction import extract_memories
from magent.tokens import estimate_tokens, truncate_to_tokens


class LifecycleRuntimeMixin:
    config: Any
    provider: Any
    extraction_provider: Any
    logger: Any
    tools: Any
    mcp: Any
    memory: Any
    cwd: str
    username: str
    project_slug: str | None
    session_id: str
    turn_count: int
    compacted_summary: str
    scratchpad: dict[str, Any]
    conversation: list[dict[str, str]]
    _subagent_runner: Any
    _spend: Any

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
        if tool_name in FILE_MUTATION_TOOLS and result.get("path"):
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
        if tool_name not in FILE_MUTATION_TOOLS or not result.get("path"):
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
        self._spend.record(cost or 0.0)

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
                parent_task_id=str(getattr(self, "execution_task_id", "")),
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
        await self.cancel_active_work()
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
        messaging = getattr(self, "messaging", None)
        if messaging:
            messaging.stop()
        # Stop all MCP server connections
        await self.mcp.stop_all()

    async def cancel_active_work(self) -> None:
        """Cancel in-flight tool work before accepting another interactive prompt."""
        await self.tools.cancel_active()
