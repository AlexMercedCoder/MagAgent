from __future__ import annotations

import logging
import sys
from types import SimpleNamespace

import pytest

from magent.agent_runtime import support
from magent.agent_runtime.context import ContextRuntimeMixin
from magent.agent_runtime.lifecycle import LifecycleRuntimeMixin


class Calls:
    def __init__(self) -> None:
        self.items: list[tuple] = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.items.append((name, args, kwargs))

        return record


class Runtime(ContextRuntimeMixin, LifecycleRuntimeMixin):
    pass


def runtime() -> Runtime:
    value = Runtime()
    value.config = SimpleNamespace(
        tool_use_enforcement="auto",
        repo_map_budget_tokens=100,
        skill_budget_tokens=100,
        keep_recent_turns=2,
        write_every_n_turns=2,
        stream_tokens=True,
        compact_every_n_turns=2,
        max_history_tokens=1,
        selective_tools=False,
        auto_write=True,
        get=lambda *_args, **kwargs: kwargs.get("default"),
    )
    value.provider = SimpleNamespace(
        provider_id="deepseek",
        model="deepseek-chat",
        display_name="DeepSeek",
        _base_kwargs={"api_base": "test"},
    )
    value.extraction_provider = SimpleNamespace(as_extract_fn=lambda: object())
    value.memory = SimpleNamespace(
        available=True,
        recall=lambda query: f"memory:{query}",
        write_memories=lambda items, project: len(items),
        write_session_summary=lambda *_args: None,
    )
    value.repo_map = SimpleNamespace(relevant_slice=lambda *_args: "repo slice")
    value.skill_registry = SimpleNamespace(build_skill_context=lambda *_args, **_kwargs: "skill")
    value.logger = Calls()
    value.tools = SimpleNamespace(
        show_tool_calls=False,
        get_tool_definitions=lambda: [{"name": "all"}],
        get_tool_definitions_for_message=lambda _message: [{"name": "selected"}],
        cancel_active=lambda: _async_none(),
    )
    value.mcp = SimpleNamespace(
        get_tool_definitions=lambda: [{"name": "mcp"}], stop_all=_async_none
    )
    value.messaging = None
    value.cwd = "/tmp/project"
    value.username = "alex"
    value.project_slug = "project"
    value.session_id = "session-1"
    value.turn_count = 2
    value.compacted_summary = ""
    value.scratchpad = {"files_touched": [], "commands_run": [], "decisions": []}
    value.conversation = [
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new request"},
        {"role": "assistant", "content": "new answer"},
    ]
    value._subagent_runner = None
    value._spend_tracker = SimpleNamespace(record=lambda _cost: None)
    return value


async def _async_none(*_args, **_kwargs):
    return None


@pytest.mark.parametrize(
    ("setting", "model", "expected"),
    [
        (True, "plain", True),
        (False, "deepseek", False),
        (["qwen"], "qwen-coder", True),
        ("always", "plain", True),
        ("off", "deepseek", False),
        ("auto", "deepseek-chat", True),
    ],
)
def test_context_enforcement_modes(setting, model, expected) -> None:
    value = runtime()
    value.config.tool_use_enforcement = setting
    value.provider.model = model
    assert value._should_inject_tool_use_enforcement() is expected


def test_context_builds_prompt_session_and_provider_parameters() -> None:
    value = runtime()
    value.compacted_summary = "older summary"
    value.scratchpad["files_touched"] = ["a.py"]
    value.scratchpad["commands_run"] = ["pytest"]
    value.messaging = SimpleNamespace(
        drain=lambda: [
            {
                "sender_name": "reviewer",
                "sender_id": "peer-1",
                "message_id": "m1",
                "message": "check this",
                "project": "project",
            }
        ]
    )
    prompt = value._build_system_prompt("fix it")
    messages = value._build_prompt_messages("fix it")
    assert "memory:fix it" in prompt
    assert "repo slice" in prompt
    assert "older summary" in prompt
    assert any("UNTRUSTED PEER" in item["content"] for item in messages)
    assert value._build_session_context().endswith("\n")
    assert value._conversation_messages_for_prompt() == value.conversation[-3:-1]
    assert value._completion_params() == {"temperature": 0.3, "max_tokens": 4096}
    assert value._provider_request_kwargs() == {"api_base": "test"}
    assert value._periodic_memory_write_due() is True
    assert value._streaming_enabled() is True


def test_context_provider_hooks_and_messaging_failure() -> None:
    value = runtime()
    value.provider.completion_params = lambda temperature, tokens: {"t": temperature, "n": tokens}
    value.provider.request_kwargs = lambda config, **kwargs: {"user": kwargs["username"]}
    assert value._completion_params(0.1, 20) == {"t": 0.1, "n": 20}
    assert value._provider_request_kwargs() == {"user": "alex"}
    value.config.write_every_n_turns = 0
    assert value._periodic_memory_write_due() is False

    class BrokenMessaging:
        def start(self):
            raise OSError("unavailable")

    value.messaging = BrokenMessaging()
    value._ensure_messaging_started()
    assert value.messaging is None
    assert value.logger.items[-1][0] == "log_activity_event"


def test_lifecycle_compacts_observes_compresses_and_prunes() -> None:
    value = runtime()
    value.conversation.append({"role": "user", "content": "latest"})
    value._maybe_compact_conversation()
    assert value.compacted_summary.startswith("Compacted")
    assert len(value.conversation) == 2

    value._observe_tool_result("write_file", {}, {"path": "a.py"})
    value._observe_tool_result("run_shell", {"command": "pytest"}, {})
    value._observe_tool_result("run_shell", {}, {"permission_required": True, "error": "ask"})
    assert "a.py" in value.scratchpad["files_touched"]
    assert "pytest" in value.scratchpad["commands_run"]
    assert value.scratchpad["permission_failures"]

    compressed = value._compress_tool_result(
        "search_codebase",
        {"content": "x " * 5000, "matches": list(range(70)), "entries": list(range(90))},
    )
    assert '"truncated": true' in compressed
    messages = [{"role": "tool", "name": "read_file", "content": "a.py old contents"}]
    value._prune_stale_tool_results(messages, "write_file", {"path": "a.py"})
    assert messages[0]["content"].startswith("[pruned stale")
    assert value._tool_definitions("task") == [{"name": "all"}, {"name": "mcp"}]
    value.config.selective_tools = True
    assert value._tool_definitions("task")[0]["name"] == "selected"


def test_lifecycle_usage_memory_and_shutdown(monkeypatch) -> None:
    value = runtime()
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    fake_litellm = SimpleNamespace(completion_cost=lambda **_kwargs: 0.02)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    value._log_llm_usage(SimpleNamespace(usage=usage))
    assert any(item[0] == "log_token_usage" for item in value.logger.items)

    async def extracted(*_args, **_kwargs):
        return [{"type": "fact", "content": "remember"}]

    monkeypatch.setattr("magent.agent_runtime.lifecycle.extract_memories", extracted)

    async def exercise() -> None:
        await value._maybe_write_memories()
        await value.end_session()

    import asyncio

    asyncio.run(exercise())
    names = [item[0] for item in value.logger.items]
    assert "log_memory_write" in names
    assert "log_session_end" in names


@pytest.mark.asyncio
async def test_lifecycle_reuses_subagent_runner(monkeypatch) -> None:
    value = runtime()

    class Runner:
        created = 0

        def __init__(self, **_kwargs):
            Runner.created += 1

        async def spawn(self, task_id, description):
            return SimpleNamespace(done=True, error="", result=f"{task_id}:{description}")

    monkeypatch.setattr("magent.subagents.SubAgentRunner", Runner)
    assert await value.spawn_subagent("review", "inspect") == "review:inspect"
    assert await value.spawn_subagent("verify", "test") == "verify:test"
    assert Runner.created == 1


def test_runtime_support_helpers_cover_diagnostics_and_recovery() -> None:
    assert support._strip_pseudo_tool_markup("plain") == "plain"
    assert support._tool_call_description("run_shell", {"command": "pytest"}) == "pytest"
    assert support._tool_call_description("web_search", {"query": "topic"}) == "topic"
    assert support._tool_call_description("web_fetch", {"url": "https://example.com"})
    assert support._tool_call_description("unknown", {}) == ""

    assert support._tool_activity_label({}) == ""
    assert (
        support._tool_activity_label({"activity": {"phase": "edit", "intent": "artifact"}})
        == "edit: artifact"
    )
    assert support._tool_activity_label({"activity": {"expected": "done"}}) == "done"

    metadata = support._tool_timing_metadata(
        "write_file",
        {"path": "a.py", "activity": {"phase": "edit"}},
        {"ok": False, "path": "a.py", "bytes": 3, "error": "failed"},
    )
    assert metadata["description"] == "a.py"
    assert metadata["activity"] == {"phase": "edit"}
    assert metadata["bytes"] == 3
    assert metadata["error"] == "failed"

    missing = support._tool_failure_steer(
        "write_file", {"path": "a.py"}, "Missing required argument 'content'", 1
    )
    placeholder = support._tool_failure_steer(
        "write_file", {"path": "a.py"}, "Suspicious write_file payload", 2
    )
    generic = support._tool_failure_steer("run_shell", {"command": "bad"}, "failed", 1)
    assert "complete final `content`" in missing
    assert "placeholder" in placeholder
    assert "change strategy" in generic

    assert support._is_missing_write_file_content("read_file", {"ok": False}) is False
    assert support._is_missing_write_file_content(
        "write_file", {"ok": False, "error": "missing required argument for write_file: content"}
    )
    assert support._clean_recovered_artifact_content("", "a.html") == ""
    assert support._clean_recovered_artifact_content("a.html", "a.html") == ""
    assert support._clean_recovered_artifact_content("not html", "a.html") == ""
    assert (
        support._clean_recovered_artifact_content("```html\n<html>ok</html>\n```", "a.html")
        == "<html>ok</html>"
    )
    assert support._format_duration(50) == "50ms"
    assert support._format_duration(1500) == "1.5s"
    assert support._format_duration(65_000) == "1m 5s"
    assert support.reflow(" a\n b ") == "a b"

    support._quiet_litellm_network_warnings()
    support._quiet_litellm_network_warnings()
    noise_filter = support._LiteLLMNoiseFilter()
    noisy = logging.LogRecord(
        "LiteLLM", logging.WARNING, "", 0, "Failed to fetch remote model cost map", (), None
    )
    quiet = logging.LogRecord("LiteLLM", logging.INFO, "", 0, "normal", (), None)
    assert noise_filter.filter(noisy) is False
    assert noise_filter.filter(quiet) is True
