from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from magent.agent import AgentSession


class FakeLogger:
    def __init__(self):
        self.tool_calls = []
        self.pruned = []

    def log_tool_call(self, *args):
        self.tool_calls.append(args)

    def log_context_pruned(self, *args):
        self.pruned.append(args)

    def log_token_usage(self, *args, **kwargs):
        return None

    def log_timing(self, *args, **kwargs):
        return None

    def log_user_turn(self, *args, **kwargs):
        return None

    def log_assistant_turn(self, *args, **kwargs):
        return None


class FakeTools:
    def __init__(self):
        self.calls = []
        self.show_tool_calls = False

    def get_tool_definitions(self):
        return [{"function": {"name": "write_file"}}]

    async def dispatch(self, name, args):
        self.calls.append((name, args))
        return {"ok": True, "path": "/repo/app.py", "content": "done"}


class FakeDeniedTools(FakeTools):
    def get_tool_definitions(self):
        return [{"function": {"name": "run_shell"}}]

    async def dispatch(self, name, args):
        return {
            "ok": False,
            "error": "Permission denied by user",
            "permission_required": False,
            "permission_tier": 3,
            "permission_reason": "user-denied",
        }


class FakeMCP:
    def get_tool_definitions(self):
        return []

    def is_mcp_tool(self, name):
        return False


class FakeConfig:
    selective_tools = False
    allowed_shell_patterns = []
    prune_stale_tool_results = True
    prompt_caching = True
    prompt_cache_key_scope = "project"
    prompt_cache_retention = ""
    repo_map_budget_tokens = 1200
    skill_budget_tokens = 2000


def make_session() -> AgentSession:
    session = AgentSession.__new__(AgentSession)
    session._mcp_start_task = None
    session.tools = FakeTools()
    session.mcp = FakeMCP()
    session.config = FakeConfig()
    session.provider = SimpleNamespace(_base_kwargs={}, provider_id="fake", model="fake")
    session.logger = FakeLogger()
    session.scratchpad = {"files_touched": [], "commands_run": [], "decisions": []}
    session.turn_count = 0
    return session


def tool_call_message() -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="write_file", arguments='{"path": "app.py"}'),
    )
    return SimpleNamespace(
        content="",
        tool_calls=[tool_call],
        model_dump=lambda: {
            "role": "assistant",
            "provider_specific_fields": {"internal": True},
            "tool_calls": [
                {
                    "id": "call_1",
                    "provider_specific_fields": {"internal": True},
                }
            ],
        },
    )


def shell_tool_call_message() -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_shell",
        function=SimpleNamespace(name="run_shell", arguments='{"command": "pip install package"}'),
    )
    return SimpleNamespace(
        content="",
        tool_calls=[tool_call],
        model_dump=lambda: {
            "role": "assistant",
            "tool_calls": [{"id": "call_shell"}],
        },
    )


def final_message() -> SimpleNamespace:
    return SimpleNamespace(
        content="finished",
        tool_calls=[],
        model_dump=lambda: {"role": "assistant", "content": "finished"},
    )


def final_message_with_content(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=text,
        tool_calls=[],
        model_dump=lambda: {"role": "assistant", "content": text},
    )


def dsml_write_file_message() -> SimpleNamespace:
    text = (
        'Before tool.\n<｜DSML｜tool_calls>\n<｜DSML｜invoke name="write_file">\n'
        '<｜DSML｜parameter name="path" string="true">history-of-cheese.html</｜DSML｜parameter>\n'
        '<｜DSML｜parameter name="content" string="true">&lt;!DOCTYPE html&gt;\n'
        "<html><body><h1>Cheese</h1></body></html></｜DSML｜parameter>"
    )
    return final_message_with_content(text)


def truncated_dsml_message() -> SimpleNamespace:
    return final_message_with_content(
        'Before tool.\n<｜DSML｜tool_calls>\n<｜DSML｜invoke name="write_file">\n'
        '<｜DSML｜parameter name="path" string="true">history-of-cheese.html'
    )


def empty_final_message() -> SimpleNamespace:
    return SimpleNamespace(
        content="",
        tool_calls=[],
        model_dump=lambda: {"role": "assistant", "content": ""},
    )


@pytest.mark.asyncio
async def test_run_tool_loop_dispatches_tool_and_returns_final_text(monkeypatch) -> None:
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=tool_call_message())]),
        SimpleNamespace(choices=[SimpleNamespace(message=final_message())]),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()

    text, messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write file"}],
        "write file",
    )

    assert text == "finished"
    assert tool_count == 1
    assert any(message.get("role") == "tool" for message in messages)
    assert session.scratchpad["files_touched"] == ["/repo/app.py"]
    assert session.logger.tool_calls[0][0] == "write_file"


@pytest.mark.asyncio
async def test_run_tool_loop_summarizes_successful_tools_when_provider_is_silent(monkeypatch) -> None:
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=tool_call_message())]),
        SimpleNamespace(choices=[SimpleNamespace(message=empty_final_message())]),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()

    text, _messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write file"}],
        "write file",
    )

    assert tool_count == 1
    assert text.startswith("Done.")
    assert "/repo/app.py" in text


@pytest.mark.asyncio
async def test_run_tool_loop_stops_repeated_identical_tool_calls(monkeypatch) -> None:
    async def fake_acompletion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=tool_call_message())])

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()

    text, _messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write file"}],
        "write file",
    )

    assert "repeated the same request" in text
    assert tool_count == 4
    assert len(session.tools.calls) == 3


@pytest.mark.asyncio
async def test_run_tool_loop_executes_dsml_pseudo_tool_markup(monkeypatch) -> None:
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=dsml_write_file_message())]),
        SimpleNamespace(choices=[SimpleNamespace(message=final_message())]),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()

    text, messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write cheese page"}],
        "write cheese page",
    )

    assert text == "finished"
    assert tool_count == 1
    assert session.tools.calls[0][0] == "write_file"
    assert session.tools.calls[0][1]["path"] == "history-of-cheese.html"
    assert "<!DOCTYPE html>" in session.tools.calls[0][1]["content"]
    assert session.scratchpad["files_touched"] == ["/repo/app.py"]
    assert not any("<｜DSML｜tool_calls>" in str(message.get("content", "")) for message in messages)


@pytest.mark.asyncio
async def test_run_tool_loop_retries_truncated_dsml_without_dumping_content(monkeypatch) -> None:
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=truncated_dsml_message())]),
        SimpleNamespace(choices=[SimpleNamespace(message=final_message())]),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()

    text, messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write cheese page"}],
        "write cheese page",
    )

    assert text == "finished"
    assert tool_count == 0
    assert session.tools.calls == []
    assert any("incomplete DSML tool markup" in str(message.get("content", "")) for message in messages)
    assert not any("history-of-cheese.html" in str(message.get("content", "")) for message in messages if message.get("role") == "assistant")


@pytest.mark.asyncio
async def test_run_tool_loop_sanitizes_provider_specific_message_fields(monkeypatch) -> None:
    calls = []
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=tool_call_message())]),
        SimpleNamespace(choices=[SimpleNamespace(message=final_message())]),
    ]

    async def fake_acompletion(**kwargs):
        calls.append(kwargs["messages"])
        return responses.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()

    await session._run_tool_loop([{"role": "user", "content": "write file"}], "write file")

    second_request = calls[1]
    assert all("provider_specific_fields" not in str(message) for message in second_request)
    assert any(message.get("role") == "assistant" for message in second_request)
    assert any(message.get("role") == "tool" for message in second_request)


@pytest.mark.asyncio
async def test_run_tool_loop_returns_provider_error(monkeypatch) -> None:
    async def fake_acompletion(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()

    text, messages, tool_count = await session._run_tool_loop([{"role": "user", "content": "hi"}])

    assert text == "[Provider error: provider down]"
    assert messages == [{"role": "user", "content": "hi"}]
    assert tool_count == 0


def test_prune_stale_tool_results_replaces_old_reads() -> None:
    session = make_session()
    messages = [
        {"role": "tool", "name": "read_file", "content": '{"path": "/repo/app.py", "content": "old"}'},
        {"role": "tool", "name": "search_codebase", "content": "/repo/app.py:old"},
    ]

    session._prune_stale_tool_results(
        messages,
        "write_file",
        {"ok": True, "path": "/repo/app.py"},
    )

    assert messages[0]["content"].startswith("[pruned stale read_file")
    assert messages[1]["content"] == "/repo/app.py:old"
    assert session.logger.pruned


def test_build_prompt_messages_separates_stable_and_volatile_context() -> None:
    session = make_session()
    session.memory = SimpleNamespace(available=False)
    session.repo_map = SimpleNamespace(relevant_slice=lambda *_args: "## Repo Map\n- app.py")
    session.skill_registry = SimpleNamespace(build_skill_context=lambda *_args, **_kwargs: "")
    session.compacted_summary = ""
    session.conversation = [{"role": "user", "content": "previous"}]

    messages = session._build_prompt_messages("current task")

    assert messages[0]["role"] == "system"
    assert "You are MagAgent" in messages[0]["content"]
    assert "Repo Map" not in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "Repo Map" in messages[1]["content"]


@pytest.mark.asyncio
async def test_stream_chat_does_not_make_second_finalizing_model_call(monkeypatch) -> None:
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=final_message_with_content("final answer"))]
        )

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()
    session.username = "user"
    session.cwd = "/repo"
    session.project_slug = "repo"
    session.session_id = "session"
    session.turn_count = 0
    session.conversation = []
    session.memory = SimpleNamespace(available=False)
    session.repo_map = SimpleNamespace(relevant_slice=lambda *_args: "")
    session.skill_registry = SimpleNamespace(build_skill_context=lambda *_args, **_kwargs: "")
    session.compacted_summary = ""
    session.config.write_every_n_turns = 999
    session.config.keep_recent_turns = 6
    session.config.compact_every_n_turns = 10
    session.config.max_history_tokens = 6000

    chunks = [chunk async for chunk in session.stream_chat("hello")]

    assert chunks == ["final answer"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_stream_chat_executes_dsml_pseudo_tool_markup(monkeypatch) -> None:
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=dsml_write_file_message())]),
        SimpleNamespace(choices=[SimpleNamespace(message=final_message_with_content("wrote file"))]),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()
    session.username = "user"
    session.cwd = "/repo"
    session.project_slug = "repo"
    session.session_id = "session"
    session.turn_count = 0
    session.conversation = []
    session.memory = SimpleNamespace(available=False)
    session.repo_map = SimpleNamespace(relevant_slice=lambda *_args: "")
    session.skill_registry = SimpleNamespace(build_skill_context=lambda *_args, **_kwargs: "")
    session.compacted_summary = ""
    session.config.write_every_n_turns = 999
    session.config.keep_recent_turns = 6
    session.config.compact_every_n_turns = 10
    session.config.max_history_tokens = 6000

    chunks = [chunk async for chunk in session.stream_chat("write cheese page")]

    assert chunks == ["wrote file"]
    assert session.tools.calls[0][0] == "write_file"
    assert session.tools.calls[0][1]["path"] == "history-of-cheese.html"
    assert "<｜DSML｜tool_calls>" not in "".join(chunks)


@pytest.mark.asyncio
async def test_run_tool_loop_stops_after_user_denies_permission(monkeypatch) -> None:
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=shell_tool_call_message())])

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()
    session.tools = FakeDeniedTools()

    text, messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "install package"}],
        "install package",
    )

    assert tool_count == 1
    assert len(calls) == 1
    assert text.startswith("Stopped because you denied")
    assert messages[-1]["role"] == "assistant"
