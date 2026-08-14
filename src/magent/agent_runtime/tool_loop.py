"""Provider rounds, bounded tool execution, and artifact recovery."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from rich.markup import escape

from magent.activity_events import activity_event
from magent.agent_runtime.support import (
    ARTIFACT_RECOVERY_MAX_TOKENS,
    FILE_MUTATION_TOOLS,
    MAX_FAILED_SAME_TOOL_PER_TURN,
    MAX_IDENTICAL_TOOL_CALLS_PER_TURN,
    MAX_MODEL_ROUNDS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    _clean_recovered_artifact_content,
    _contains_pseudo_tool_markup,
    _extract_pseudo_tool_calls,
    _format_duration,
    _is_missing_write_file_content,
    _sanitize_message,
    _sanitize_messages,
    _strip_pseudo_tool_markup,
    _tool_activity_label,
    _tool_call_description,
    _tool_call_fingerprint,
    _tool_failure_steer,
    _tool_timing_metadata,
    console,
)
from magent.artifact_contracts import (
    artifact_audit_note,
    infer_expected_artifacts,
    verify_expected_artifacts,
)
from magent.hooks import run_hooks_async
from magent.tools.registry import normalize_tool_activity, strip_tool_activity


class ToolLoopRuntimeMixin:
    config: Any
    provider: Any
    logger: Any
    tools: Any
    mcp: Any
    conversation: list[dict[str, str]]
    scratchpad: dict[str, Any]
    turn_count: int
    _mcp_start_attempted: bool
    _mcp_start_task: Any
    _build_prompt_messages: Any
    _completion_params: Any
    _provider_request_kwargs: Any
    _cwd: Any
    _drain_peer_context: Any
    _ensure_messaging_started: Any
    _periodic_memory_write_due: Any
    _spend: Any
    _streaming_enabled: Any
    _maybe_compact_conversation: Any
    _maybe_write_memories: Any
    _observe_tool_result: Any
    _prune_stale_tool_results: Any
    _tool_definitions: Any
    _log_llm_usage: Any
    _mcp_tool_allowed: Any
    _compress_tool_result: Any
    _resolve_agent_message: Any

    async def _model_round(
        self,
        messages: list[dict[str, Any]],
        tool_defs: list[dict[str, Any]] | None,
        *,
        on_text: Callable[[str], None] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Any:
        """One model call, streaming when a consumer is listening.

        `stream_chat` previously yielded the whole answer as a single chunk —
        litellm was never called with `stream=True` — so the caller waited for
        the full response before seeing anything. Deltas are forwarded to
        `on_text` as they arrive and the chunks are reassembled into the same
        response object the non-streaming path returns, so the tool loop below
        is unchanged.
        """
        import litellm

        litellm.suppress_debug_info = True
        request: dict[str, Any] = {
            "messages": _sanitize_messages(messages),
            **self._completion_params(temperature, max_tokens),
            **self._provider_request_kwargs(),
        }
        if tool_defs:
            request["tools"] = tool_defs
            request["tool_choice"] = "auto"

        if on_text is None or not self._streaming_enabled():
            return await litellm.acompletion(**request)

        chunks: list[Any] = []
        try:
            stream = await litellm.acompletion(**request, stream=True)
            if not hasattr(stream, "__aiter__"):
                # Provider (or test double) ignored stream=True and returned a
                # complete response. Use it rather than paying for a second call.
                return stream
            async for chunk in stream:
                chunks.append(chunk)
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) if delta else None
                if text:
                    on_text(text)
        except Exception:
            if not chunks:
                # Nothing arrived: fall back so a provider that cannot stream
                # still answers.
                return await litellm.acompletion(**request)
            raise

        rebuilt = litellm.stream_chunk_builder(chunks, messages=request["messages"])
        if rebuilt is None:
            return await litellm.acompletion(**request)
        return rebuilt

    async def _run_tool_loop(
        self,
        messages: list[dict[str, Any]],
        user_message: str = "",
        *,
        narrate: bool = False,
        on_text: Callable[[str], None] | None = None,
    ) -> tuple[str, list[dict[str, Any]], int]:
        """Run the LLM + tool loop. Returns (final_text, messages, tool_call_count).

        `narrate` turns on the interactive console commentary the streaming
        path shows; headless callers (gateway, sub-agents) leave it off.
        """
        turn_started = time.monotonic()
        if narrate:
            console.print("[dim]thinking...[/dim]")
        # Wait for MCP servers to finish connecting (if still starting)
        await self._ensure_mcp_started()

        # Merge built-in tools + MCP tools
        tool_defs = self._tool_definitions(user_message)
        total_tool_calls = 0
        pseudo_retry_count = 0
        repeated_tool_calls: dict[str, int] = {}
        failed_tool_counts: dict[str, int] = {}
        failed_file_mutations: dict[str, dict[str, str]] = {}
        llm_round = 0

        while True:
            try:
                import litellm

                litellm.suppress_debug_info = True

                llm_round += 1
                if llm_round > self._max_model_rounds_per_turn():
                    content = self._finalize_turn_response(
                        f"Stopped after {self._max_model_rounds_per_turn()} model rounds to avoid an agent loop.",
                        failed_file_mutations,
                    )
                    if narrate:
                        console.print(
                            f"[yellow]  stop {self._stop_console_summary(content)}[/yellow]"
                        )
                    messages.append({"role": "assistant", "content": content})
                    return content, messages, total_tool_calls
                budget = self._spend.check()
                if not budget.ok:
                    content = self._finalize_turn_response(budget.reason, failed_file_mutations)
                    if narrate:
                        console.print(f"[red]  stop {budget.reason}[/red]")
                    messages.append({"role": "assistant", "content": content})
                    return content, messages, total_tool_calls
                if budget.warning and narrate:
                    console.print(f"[yellow]  budget {budget.warning}[/yellow]")

                llm_started = time.monotonic()
                self._log_model_activity_event("model_round_started", llm_round)
                response = await self._await_activity(
                    self._model_round(messages, tool_defs, on_text=on_text),
                    label=f"model round {llm_round}",
                    narrate=narrate,
                    event_kind="model",
                    round_number=llm_round,
                )
                llm_elapsed = self._log_timing(
                    "llm_call",
                    llm_started,
                    metadata={
                        "round": llm_round,
                        "turn_elapsed_ms": round((time.monotonic() - turn_started) * 1000, 2),
                        "tool_calls_so_far": total_tool_calls,
                        "messages": len(messages),
                    },
                )
                if narrate and self.tools.show_tool_calls:
                    console.print(
                        f"[dim]  time model round {llm_round} responded in "
                        f"{_format_duration(llm_elapsed)} ({total_tool_calls} tools so far)[/dim]"
                    )
                self._log_llm_usage(response)
                self._log_model_activity_event(
                    "model_round_finished", llm_round, duration_ms=llm_elapsed
                )
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
                        repeat_message = self._record_tool_call_or_stop(
                            repeated_tool_calls,
                            tool_name,
                            tool_args,
                            total_tool_calls,
                        )
                        if repeat_message:
                            if narrate:
                                console.print(f"[yellow]  stop {repeat_message}[/yellow]")
                            messages.append({"role": "assistant", "content": repeat_message})
                            return repeat_message, messages, total_tool_calls
                        tool_started = time.monotonic()
                        result = await self._dispatch_tool_call(tool_name, tool_args)
                        self._log_timing(
                            f"tool.{tool_name}",
                            tool_started,
                            metadata=_tool_timing_metadata(tool_name, tool_args, result),
                        )
                        self._record_file_mutation_result(
                            failed_file_mutations, tool_name, tool_args, result
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    f"Parsed and executed assistant-emitted tool markup for `{tool_name}`. "
                                    f"Tool result:\n{self._compress_tool_result(tool_name, result)}"
                                ),
                            }
                        )
                        recovered = await self._maybe_recover_missing_write_file_content(
                            messages,
                            tool_args,
                            result,
                            failed_file_mutations,
                        )
                        if recovered:
                            messages.append({"role": "assistant", "content": recovered})
                            return recovered, messages, total_tool_calls
                        if self._permission_denied_by_user(result):
                            content = self._permission_denial_summary(tool_name, tool_args)
                            messages.append({"role": "assistant", "content": content})
                            return content, messages, total_tool_calls
                        stop_message = self._tool_failure_steer_or_stop(
                            messages,
                            tool_name,
                            tool_args,
                            result,
                            failed_tool_counts,
                        )
                        if stop_message:
                            recovered = await self._maybe_recover_missing_write_file_content(
                                messages,
                                tool_args,
                                result,
                                failed_file_mutations,
                            )
                            if recovered:
                                messages.append({"role": "assistant", "content": recovered})
                                return recovered, messages, total_tool_calls
                            content = self._finalize_turn_response(
                                stop_message, failed_file_mutations
                            )
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
                            "content": _strip_pseudo_tool_markup(content)
                            or "Tool markup was incomplete.",
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
                content = self._finalize_turn_response(
                    content,
                    failed_file_mutations,
                    user_message=user_message,
                )
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
                repeat_message = self._record_tool_call_or_stop(
                    repeated_tool_calls,
                    tool_name,
                    tool_args,
                    total_tool_calls,
                )
                if repeat_message:
                    if narrate:
                        console.print(f"[yellow]  stop {repeat_message}[/yellow]")
                    messages.append({"role": "assistant", "content": repeat_message})
                    return repeat_message, messages, total_tool_calls

                activity_label = _tool_activity_label(tool_args)
                if narrate and activity_label and self.tools.show_tool_calls:
                    console.print(f"[dim]    intent: {escape(activity_label)}[/dim]")
                tool_started = time.monotonic()
                result = await self._await_activity(
                    self._execute_tool_call(tool_name, tool_args),
                    label=tool_name,
                    narrate=narrate,
                    event_kind="tool",
                    tool_name=tool_name,
                    tool_args=tool_args,
                )
                result_str = self._compress_tool_result(tool_name, result)
                tool_elapsed = self._log_timing(
                    f"tool.{tool_name}",
                    tool_started,
                    metadata=_tool_timing_metadata(tool_name, tool_args, result),
                )
                if narrate and self.tools.show_tool_calls:
                    console.print(
                        f"[dim]    -> {tool_name} finished in {_format_duration(tool_elapsed)} "
                        f"({self._tool_result_label(result)})[/dim]"
                    )
                self._log_tool_activity_event(
                    tool_name,
                    tool_args,
                    result,
                    duration_ms=(time.monotonic() - tool_started) * 1000,
                )
                self._record_file_mutation_result(
                    failed_file_mutations, tool_name, tool_args, result
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                        "name": tool_name,
                    }
                )
                recovered = await self._maybe_recover_missing_write_file_content(
                    messages,
                    tool_args,
                    result,
                    failed_file_mutations,
                )
                if recovered:
                    messages.append({"role": "assistant", "content": recovered})
                    return recovered, messages, total_tool_calls
                if self._permission_denied_by_user(result):
                    content = self._permission_denial_summary(tool_name, tool_args)
                    messages.append({"role": "assistant", "content": content})
                    return content, messages, total_tool_calls
                stop_message = self._tool_failure_steer_or_stop(
                    messages,
                    tool_name,
                    tool_args,
                    result,
                    failed_tool_counts,
                )
                if stop_message:
                    recovered = await self._maybe_recover_missing_write_file_content(
                        messages,
                        tool_args,
                        result,
                        failed_file_mutations,
                    )
                    if recovered:
                        messages.append({"role": "assistant", "content": recovered})
                        return recovered, messages, total_tool_calls
                    content = self._finalize_turn_response(stop_message, failed_file_mutations)
                    if narrate:
                        console.print(
                            f"[yellow]  stop {self._stop_console_summary(stop_message)}[/yellow]"
                        )
                    messages.append({"role": "assistant", "content": content})
                    return content, messages, total_tool_calls
                if self.config.prune_stale_tool_results:
                    self._prune_stale_tool_results(messages, tool_name, result)

        return "", messages, total_tool_calls  # unreachable

    async def _run_turn(
        self,
        user_message: str,
        *,
        narrate: bool = False,
        on_text: Callable[[str], None] | None = None,
    ) -> tuple[str, int]:
        """Run one complete turn: prompt, tool loop, history, logging, memory.

        `chat` and `stream_chat` used to be ~600-line near-copies of the same
        loop, and had already diverged: periodic memory writes fired on only 2
        of stream_chat's ~8 return paths, and pruning behaviour differed. There
        is one loop now, and this is the single place turn bookkeeping happens,
        so every exit path is treated identically.
        """
        self._ensure_messaging_started()
        user_message = self._resolve_agent_message(user_message)
        self.turn_count += 1
        self.logger.log_user_turn(self.turn_count, user_message)
        with suppress(Exception):
            self.logger.log_transcript("user", user_message)
        self.conversation.append({"role": "user", "content": user_message})

        messages = self._build_prompt_messages(user_message)

        try:
            response, _messages, tool_calls = await self._run_tool_loop(
                messages, user_message, narrate=narrate, on_text=on_text
            )
        except Exception as e:
            response, tool_calls = f"\n[Error: {e}]", 0

        self.conversation.append({"role": "assistant", "content": response})
        with suppress(Exception):
            self.logger.log_assistant_turn(self.turn_count, response, tool_calls)
            self.logger.log_transcript("assistant", response)

        if self._periodic_memory_write_due():
            await self._maybe_write_memories()
        self._maybe_compact_conversation()
        restore_profile = getattr(self, "_restore_turn_profile", None)
        if callable(restore_profile):
            restore_profile()

        return response, tool_calls

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
        return result.get("ok") is False and result.get("permission_reason") == "user-denied"

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

    def _max_model_rounds_per_turn(self) -> int:
        configured = int(
            getattr(self.config, "max_model_rounds_per_turn", MAX_MODEL_ROUNDS_PER_TURN)
        )
        profile = getattr(self, "profile", None)
        if profile is not None and int(profile.max_turns or 0) > 0:
            return min(configured, int(profile.max_turns))
        return configured

    def _max_tool_calls_per_turn(self) -> int:
        return int(getattr(self.config, "max_tool_calls_per_turn", MAX_TOOL_CALLS_PER_TURN))

    def _max_identical_tool_calls_per_turn(self) -> int:
        return int(
            getattr(
                self.config,
                "max_identical_tool_calls_per_turn",
                MAX_IDENTICAL_TOOL_CALLS_PER_TURN,
            )
        )

    def _max_failed_same_tool_per_turn(self) -> int:
        return int(
            getattr(self.config, "max_failed_same_tool_per_turn", MAX_FAILED_SAME_TOOL_PER_TURN)
        )

    def _doom_loop_policy(self) -> str:
        return str(getattr(self.config, "doom_loop_policy", "halt"))

    def _record_tool_call_or_stop(
        self,
        repeated_tool_calls: dict[str, int],
        tool_name: str,
        tool_args: dict[str, Any],
        total_tool_calls: int,
    ) -> str:
        max_tool_calls = self._max_tool_calls_per_turn()
        if total_tool_calls > max_tool_calls:
            message = (
                f"Stopped after {max_tool_calls} tool calls in this turn to avoid an agent loop. "
                "Say `continue` to let me resume from the current project state, or retry with a narrower request."
            )
            self.logger.log_timing(
                "tool_loop_stopped",
                0,
                turn=self.turn_count,
                metadata={"reason": "max_tool_calls", "tool": tool_name, "count": total_tool_calls},
            )
            return message

        key = _tool_call_fingerprint(tool_name, tool_args)
        repeated_tool_calls[key] = repeated_tool_calls.get(key, 0) + 1
        count = repeated_tool_calls[key]
        if count <= self._max_identical_tool_calls_per_turn():
            return ""

        desc = _tool_call_description(tool_name, tool_args)
        message = (
            f"Stopped because `{tool_name}` repeated the same request {count} times"
            + (f" ({desc})" if desc else "")
            + ". I did not continue rewriting the same target."
        )
        self.logger.log_timing(
            "tool_loop_stopped",
            0,
            turn=self.turn_count,
            metadata={
                "reason": "repeated_tool_call",
                "tool": tool_name,
                "description": desc,
                "count": count,
                "fingerprint": key,
            },
        )
        return message

    def _record_file_mutation_result(
        self,
        failed_file_mutations: dict[str, dict[str, str]],
        tool_name: str,
        tool_args: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if tool_name not in FILE_MUTATION_TOOLS:
            return
        raw_path = str(
            result.get("path") or tool_args.get("path") or tool_args.get("file_path") or ""
        )
        path = self._canonical_tool_path(raw_path)
        if not path:
            return
        if result.get("ok", True):
            failed_file_mutations.pop(path, None)
            return
        failed_file_mutations.setdefault(
            path,
            {
                "tool": tool_name,
                "error": str(result.get("error") or "tool failed")[:500],
            },
        )

    def _canonical_tool_path(self, path: str) -> str:
        if not path:
            return ""
        raw = Path(path).expanduser()
        if raw.is_absolute():
            return str(raw.resolve(strict=False))
        return str((Path(self._cwd()) / raw).resolve(strict=False))

    async def _ensure_mcp_started(self) -> None:
        """Start configured MCP servers from inside the active event loop."""
        config = getattr(self.mcp, "_config", {})
        if not config:
            return
        if self._mcp_start_task is None and not self._mcp_start_attempted:
            self._mcp_start_attempted = True
            self._mcp_start_task = asyncio.create_task(self.mcp.start_all())
        if self._mcp_start_task and not self._mcp_start_task.done():
            await self._mcp_start_task

    def _tool_failure_steer_or_stop(
        self,
        messages: list[dict[str, Any]],
        tool_name: str,
        tool_args: dict[str, Any],
        result: dict[str, Any],
        failed_tool_counts: dict[str, int],
    ) -> str:
        if result.get("ok", True):
            failed_tool_counts.pop(tool_name, None)
            return ""
        if self._permission_denied_by_user(result):
            return ""

        failed_tool_counts[tool_name] = failed_tool_counts.get(tool_name, 0) + 1
        count = failed_tool_counts[tool_name]
        error = str(result.get("error") or "tool failed")

        steer = _tool_failure_steer(tool_name, tool_args, error, count)
        if steer:
            messages.append({"role": "system", "content": steer})

        if count >= self._max_failed_same_tool_per_turn() and self._doom_loop_policy() == "halt":
            desc = _tool_call_description(tool_name, tool_args)
            self.logger.log_timing(
                "tool_loop_stopped",
                0,
                turn=self.turn_count,
                metadata={
                    "reason": "same_tool_failure",
                    "tool": tool_name,
                    "description": desc,
                    "count": count,
                    "error": error[:300],
                },
            )
            return (
                f"Stopped because `{tool_name}` failed {count} times this turn"
                + (f" ({desc})" if desc else "")
                + f". Latest error: {error}"
            )
        return ""

    def _finalize_turn_response(
        self,
        response: str,
        failed_file_mutations: dict[str, dict[str, str]],
        *,
        user_message: str = "",
    ) -> str:
        artifact_note = ""
        if user_message and getattr(self.config, "file_mutation_verifier", True):
            artifact_note = artifact_audit_note(
                verify_expected_artifacts(infer_expected_artifacts(user_message, cwd=self._cwd()))
            )
        if not failed_file_mutations or not getattr(self.config, "file_mutation_verifier", True):
            return response + artifact_note
        lines = [
            "File write verification:",
            "One or more requested file changes failed and were not later fixed:",
        ]
        for path, item in list(failed_file_mutations.items())[:5]:
            lines.append(
                f"- `{path}` via `{item.get('tool', 'file tool')}`: {item.get('error', 'failed')}"
            )
        footer = "\n".join(lines)
        if response.strip():
            return response.rstrip() + "\n\n" + footer + artifact_note
        return footer + artifact_note

    def _stop_console_summary(self, response: str) -> str:
        """Keep inline stop diagnostics short; the full response is yielded once."""
        return response.split("\n", 1)[0][:220]

    async def _maybe_recover_missing_write_file_content(
        self,
        messages: list[dict[str, Any]],
        tool_args: dict[str, Any],
        result: dict[str, Any],
        failed_file_mutations: dict[str, dict[str, str]],
    ) -> str:
        if not _is_missing_write_file_content("write_file", result):
            return ""
        path = str(
            tool_args.get("path") or tool_args.get("file_path") or result.get("path") or ""
        ).strip()
        if not path:
            return ""
        try:
            recovery_messages = _sanitize_messages(messages) + [
                {
                    "role": "system",
                    "content": (
                        "Artifact recovery mode: the previous write_file call omitted required content. "
                        f"Return ONLY the complete final file body for `{path}` as plain text. "
                        "Do not call tools. Do not include explanations, summaries, markdown fences, or the filename."
                    ),
                }
            ]
            started = time.monotonic()
            response = await self._model_round(
                recovery_messages,
                None,
                temperature=0.2,
                max_tokens=int(
                    getattr(
                        self.config,
                        "artifact_recovery_max_tokens",
                        ARTIFACT_RECOVERY_MAX_TOKENS,
                    )
                ),
            )
            self._log_timing(
                "artifact_recovery.llm_call",
                started,
                metadata={"path": path, "messages": len(recovery_messages)},
            )
            content = _clean_recovered_artifact_content(
                str(getattr(response.choices[0].message, "content", "") or ""),
                path,
            )
            if not content:
                return ""
            tool_started = time.monotonic()
            write_result = await self._dispatch_tool_call(
                "write_file", {"path": path, "content": content}
            )
            self._log_timing(
                "artifact_recovery.write_file",
                tool_started,
                metadata=_tool_timing_metadata("write_file", {"path": path}, write_result),
            )
            self._record_file_mutation_result(
                failed_file_mutations,
                "write_file",
                {"path": path, "content": content},
                write_result,
            )
            if not write_result.get("ok", True):
                return ""
            bytes_written = write_result.get("bytes")
            suffix = f" ({bytes_written} bytes)" if bytes_written is not None else ""
            return f"Recovered the artifact write and created `{write_result.get('path', path)}`{suffix}."
        except Exception as exc:
            self.logger.log_timing(
                "artifact_recovery_failed",
                0,
                turn=self.turn_count,
                metadata={"path": path, "error": str(exc)[:300]},
            )
            return ""

    def _log_timing(
        self,
        name: str,
        started: float,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> float:
        elapsed_ms = (time.monotonic() - started) * 1000
        self.logger.log_timing(name, elapsed_ms, turn=self.turn_count, metadata=metadata)
        return elapsed_ms

    def _tool_result_label(self, result: dict[str, Any]) -> str:
        if not result.get("ok", True):
            error = str(result.get("error") or "failed")
            return f"failed: {error[:90]}"
        if result.get("bytes") is not None:
            return f"{result['bytes']} bytes"
        if result.get("path"):
            return str(result["path"])
        return "ok"

    def _log_tool_activity_event(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: dict[str, Any],
        *,
        duration_ms: float | None = None,
    ) -> None:
        """Record a stable tool activity event for logs and desktop clients."""
        self.logger.log_activity_event(
            activity_event(
                "tool_finished",
                turn=self.turn_count,
                tool=tool_name,
                ok=result.get("ok", True),
                duration_ms=duration_ms,
                activity=normalize_tool_activity(tool_args),
                detail=_tool_timing_metadata(tool_name, tool_args, result),
            )
        )

    def _log_tool_started_event(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        self.logger.log_activity_event(
            activity_event(
                "tool_started",
                turn=self.turn_count,
                tool=tool_name,
                activity=normalize_tool_activity(tool_args),
                detail=_tool_timing_metadata(tool_name, tool_args, {}),
            )
        )

    def _log_model_activity_event(
        self,
        event_type: str,
        round_number: int,
        *,
        duration_ms: float | None = None,
    ) -> None:
        self.logger.log_activity_event(
            activity_event(
                event_type,  # type: ignore[arg-type]
                turn=self.turn_count,
                round_number=round_number,
                duration_ms=duration_ms,
            )
        )

    async def _await_activity(
        self,
        awaitable: Any,
        *,
        label: str,
        narrate: bool,
        event_kind: str,
        round_number: int = 0,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        interval_seconds: float = 10.0,
    ) -> Any:
        """Await work while proving liveness at a quiet, bounded cadence."""
        task = asyncio.ensure_future(awaitable)
        started = time.monotonic()
        try:
            while not task.done():
                done, _pending = await asyncio.wait({task}, timeout=interval_seconds)
                if done:
                    break
                elapsed = time.monotonic() - started
                if narrate:
                    console.print(
                        f"[dim]  still running {escape(label)} "
                        f"({_format_duration(elapsed * 1000)})[/dim]"
                    )
                if event_kind == "tool":
                    self._log_tool_progress_event(
                        tool_name,
                        tool_args or {},
                        elapsed,
                        "running",
                    )
                else:
                    self.logger.log_activity_event(
                        activity_event(
                            "model_round_started",
                            turn=self.turn_count,
                            round_number=round_number,
                            duration_ms=elapsed * 1000,
                            detail={"status": "running", "heartbeat": True},
                        )
                    )
            return await task
        except BaseException:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            raise

    def _log_tool_progress_event(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        elapsed_seconds: float,
        status: str,
    ) -> None:
        self.logger.log_activity_event(
            activity_event(
                "tool_progress",
                turn=self.turn_count,
                tool=tool_name,
                duration_ms=elapsed_seconds * 1000,
                activity=normalize_tool_activity(tool_args),
                detail={**_tool_timing_metadata(tool_name, tool_args, {}), "status": status},
            )
        )

    async def _execute_tool_call(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call and record hooks, scratchpad, and audit logs."""
        dispatch_args = strip_tool_activity(tool_args)
        self._log_tool_started_event(tool_name, tool_args)
        # Hooks run off the loop: a synchronous subprocess here blocked every
        # other task for up to the hook timeout.
        await run_hooks_async(self._cwd(), "pre_tool", {"tool": tool_name, "args": tool_args})
        if tool_name.startswith("mcp__") and not self._mcp_tool_allowed(tool_name):
            result = {
                "ok": False,
                "error": "MCP tool is outside the active agent profile capability set",
            }
        elif self.mcp.is_mcp_tool(tool_name):
            result = await self.mcp.dispatch(tool_name, dispatch_args)
        else:
            result = await self.tools.dispatch(tool_name, dispatch_args)
        await run_hooks_async(
            self._cwd(), "post_tool", {"tool": tool_name, "args": tool_args, "result": result}
        )
        if tool_name in FILE_MUTATION_TOOLS:
            await run_hooks_async(
                self._cwd(), "post_edit", {"tool": tool_name, "args": tool_args, "result": result}
            )
        if tool_name == "run_shell" and not result.get("ok", True):
            await run_hooks_async(
                self._cwd(),
                "command_failure",
                {"tool": tool_name, "args": tool_args, "result": result},
            )
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

    async def _dispatch_tool_call(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a pseudo-tool call and record its stable activity event."""
        result = await self._execute_tool_call(tool_name, tool_args)
        self._log_tool_activity_event(tool_name, tool_args, result)
        peer_context = self._drain_peer_context()
        if peer_context:
            result = dict(result)
            result["session_coordination"] = peer_context
        return result
