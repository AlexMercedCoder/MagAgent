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


class FakeTools:
    def get_tool_definitions(self):
        return [{"function": {"name": "write_file"}}]

    async def dispatch(self, name, args):
        return {"ok": True, "path": "/repo/app.py", "content": "done"}


class FakeMCP:
    def get_tool_definitions(self):
        return []

    def is_mcp_tool(self, name):
        return False


class FakeConfig:
    selective_tools = False
    allowed_shell_patterns = []
    prune_stale_tool_results = True


def make_session() -> AgentSession:
    session = AgentSession.__new__(AgentSession)
    session._mcp_start_task = None
    session.tools = FakeTools()
    session.mcp = FakeMCP()
    session.config = FakeConfig()
    session.provider = SimpleNamespace(_base_kwargs={}, provider_id="fake", model="fake")
    session.logger = FakeLogger()
    session.scratchpad = {"files_touched": [], "commands_run": [], "decisions": []}
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


def final_message() -> SimpleNamespace:
    return SimpleNamespace(
        content="finished",
        tool_calls=[],
        model_dump=lambda: {"role": "assistant", "content": "finished"},
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
