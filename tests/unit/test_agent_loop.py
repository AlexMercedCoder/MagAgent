from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from magent.agent import AgentSession


class FakeLogger:
    def __init__(self):
        self.tool_calls = []
        self.pruned = []
        self.activity_events = []

    def log_tool_call(self, *args):
        self.tool_calls.append(args)

    def log_context_pruned(self, *args):
        self.pruned.append(args)

    def log_token_usage(self, *args, **kwargs):
        return None

    def log_timing(self, *args, **kwargs):
        return None

    def log_activity_event(self, *args, **kwargs):
        self.activity_events.append((args, kwargs))
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


class FakeMissingContentTools(FakeTools):
    async def dispatch(self, name, args):
        self.calls.append((name, args))
        return {
            "ok": False,
            "error": "Missing required argument 'content' for tool write_file",
            "tool": name,
            "args": args,
            "path": args.get("path", ""),
        }


class FakeMissingThenSuccessTools(FakeTools):
    async def dispatch(self, name, args):
        self.calls.append((name, args))
        if len(self.calls) == 1:
            return {
                "ok": False,
                "error": "Missing required argument 'content' for tool write_file",
                "tool": name,
                "args": args,
                "path": args.get("path", ""),
            }
        return {
            "ok": True,
            "path": "/repo/app.py",
            "bytes": len(str(args.get("content", "")).encode()),
        }


class FakeMissingUntilContentTools(FakeTools):
    async def dispatch(self, name, args):
        self.calls.append((name, args))
        if "content" not in args:
            return {
                "ok": False,
                "error": "Missing required argument 'content' for tool write_file",
                "tool": name,
                "args": args,
                "path": args.get("path", ""),
            }
        return {
            "ok": True,
            "path": "/repo/oranges.html",
            "bytes": len(str(args.get("content", "")).encode()),
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
    max_model_rounds_per_turn = 16
    max_tool_calls_per_turn = 80
    max_identical_tool_calls_per_turn = 3
    max_failed_same_tool_per_turn = 2
    doom_loop_policy = "halt"
    tool_use_enforcement = "auto"
    file_mutation_verifier = True


def make_session() -> AgentSession:
    session = AgentSession.__new__(AgentSession)
    session._mcp_start_task = None
    session._mcp_start_attempted = False
    session.tools = FakeTools()
    session.mcp = FakeMCP()
    session.config = FakeConfig()
    session.provider = SimpleNamespace(_base_kwargs={}, provider_id="fake", model="fake")
    session.logger = FakeLogger()
    session.scratchpad = {"files_touched": [], "commands_run": [], "decisions": []}
    session.turn_count = 0
    session.cwd = "/repo"
    return session


class FakeConfiguredMCP(FakeMCP):
    def __init__(self):
        self._config = {"demo": {"command": "demo"}}
        self.started = 0

    async def start_all(self):
        self.started += 1
        return {"demo": True}


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


def tool_call_message_with_content() -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_2",
        function=SimpleNamespace(
            name="write_file",
            arguments='{"path": "app.py", "content": "<!doctype html><html><body>ok</body></html>"}',
        ),
    )
    return SimpleNamespace(
        content="",
        tool_calls=[tool_call],
        model_dump=lambda: {
            "role": "assistant",
            "tool_calls": [{"id": "call_2"}],
        },
    )


def orange_tool_call_message() -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_orange",
        function=SimpleNamespace(name="write_file", arguments='{"path": "oranges.html"}'),
    )
    return SimpleNamespace(
        content="",
        tool_calls=[tool_call],
        model_dump=lambda: {
            "role": "assistant",
            "tool_calls": [{"id": "call_orange"}],
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
async def test_dispatch_tool_call_strips_activity_but_keeps_audit_metadata(monkeypatch) -> None:
    hook_payloads = []

    def fake_run_hooks(project, event, payload):
        hook_payloads.append((project, event, payload))
        return []

    monkeypatch.setattr("magent.agent.run_hooks", fake_run_hooks)
    session = make_session()
    result = await session._dispatch_tool_call(
        "write_file",
        {
            "path": "app.py",
            "content": "print('ok')",
            "activity": {
                "phase": "creating",
                "intent": "Write the requested script",
            },
        },
    )

    original_args = {
        "path": "app.py",
        "content": "print('ok')",
        "activity": {
            "phase": "creating",
            "intent": "Write the requested script",
        },
    }
    assert result["ok"] is True
    assert session.tools.calls == [("write_file", {"path": "app.py", "content": "print('ok')"})]
    assert session.logger.tool_calls == [("write_file", original_args, True, 1)]
    assert hook_payloads[0][1] == "pre_tool"
    assert hook_payloads[0][2]["args"]["activity"]["phase"] == "creating"
    event_args, _event_kwargs = session.logger.activity_events[0]
    assert event_args[0]["type"] == "tool_finished"
    assert event_args[0]["activity"]["intent"] == "Write the requested script"


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


def test_tool_budget_stop_message_suggests_continue() -> None:
    session = make_session()
    session.config.max_tool_calls_per_turn = 1

    message = session._record_tool_call_or_stop({}, "write_file", {"path": "app.py"}, 2)

    assert "Stopped after 1 tool calls" in message
    assert "continue" in message


def test_tool_call_fingerprint_ignores_activity_metadata() -> None:
    from magent.agent import _tool_call_fingerprint

    base = _tool_call_fingerprint("read_file", {"path": "app.py"})
    with_activity = _tool_call_fingerprint(
        "read_file",
        {
            "path": "app.py",
            "activity": {
                "phase": "inspect",
                "intent": "Check the current implementation.",
            },
        },
    )

    assert base == with_activity


@pytest.mark.asyncio
async def test_ensure_mcp_started_lazily_inside_active_loop() -> None:
    session = make_session()
    mcp = FakeConfiguredMCP()
    session.mcp = mcp

    await session._ensure_mcp_started()

    assert mcp.started == 1
    assert session._mcp_start_attempted is True


def test_finalize_turn_response_reports_missing_expected_artifact(tmp_path) -> None:
    session = make_session()
    session.cwd = str(tmp_path)

    response = session._finalize_turn_response(
        "Done.",
        {},
        user_message="create a page named cheese.html",
    )

    assert "Artifact verification" in response
    assert "cheese.html" in response


@pytest.mark.asyncio
async def test_run_tool_loop_stops_repeated_missing_write_content(monkeypatch) -> None:
    async def fake_acompletion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=tool_call_message())])

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()
    session.tools = FakeMissingContentTools()

    text, messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write file"}],
        "write file",
    )

    assert tool_count == 2
    assert len(session.tools.calls) == 2
    assert "Missing required argument 'content'" in text
    assert "File write verification" in text
    assert any("Do not repeat `write_file` with only `path`" in str(m.get("content", "")) for m in messages)
    assert any("do not call research/search/read tools" in str(m.get("content", "")) for m in messages)


@pytest.mark.asyncio
async def test_file_verifier_clears_relative_failure_after_absolute_success(monkeypatch) -> None:
    html = "<!doctype html><html><body><h1>Recovered</h1></body></html>"
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=tool_call_message())]),
        SimpleNamespace(choices=[SimpleNamespace(message=final_message_with_content(html))]),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()
    session.cwd = "/repo"
    session.tools = FakeMissingThenSuccessTools()

    text, _messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write file"}],
        "write file",
    )

    assert tool_count == 1
    assert "Recovered the artifact write" in text
    assert "File write verification" not in text


@pytest.mark.asyncio
async def test_run_tool_loop_recovers_missing_write_content_with_no_tools_artifact(monkeypatch) -> None:
    calls = []
    html = "<!doctype html><html><body><h1>Oranges</h1></body></html>"

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(choices=[SimpleNamespace(message=orange_tool_call_message())])
        assert "tools" not in kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=final_message_with_content(html))])

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(acompletion=fake_acompletion, suppress_debug_info=False),
    )
    session = make_session()
    session.cwd = "/repo"
    session.tools = FakeMissingUntilContentTools()

    text, _messages, tool_count = await session._run_tool_loop(
        [{"role": "user", "content": "write oranges page"}],
        "write oranges page",
    )

    assert tool_count == 1
    assert "Recovered the artifact write" in text
    assert "File write verification" not in text
    assert session.tools.calls[-1] == (
        "write_file",
        {"path": "oranges.html", "content": html},
    )


def test_recovered_artifact_content_rejects_filename_placeholder() -> None:
    from magent.agent import _clean_recovered_artifact_content, _is_missing_write_file_content

    assert _clean_recovered_artifact_content("oranges.html", "oranges.html") == ""
    assert _clean_recovered_artifact_content("```html\n<html>ok</html>\n```", "oranges.html") == "<html>ok</html>"
    assert _is_missing_write_file_content(
        "write_file",
        {"ok": False, "error": "Missing required arguments for write_file: content"},
    )


def test_deepseek_prompt_gets_tool_use_enforcement() -> None:
    session = make_session()
    session.provider = SimpleNamespace(_base_kwargs={}, provider_id="opencode-go", model="deepseek-v4-flash")

    prompt = session._build_stable_prompt()

    assert "Tool-Use Enforcement" in prompt
    assert "`path` and complete `content`" in prompt


def test_static_prompt_respects_new_unrelated_folder_requests() -> None:
    session = make_session()

    prompt = session._build_stable_prompt()

    assert "new folder" in prompt
    assert "unrelated project" in prompt
    assert "existing sibling project" in prompt


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
