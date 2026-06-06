from __future__ import annotations

from types import SimpleNamespace

from magent.agent import AgentSession


def test_prunes_stale_file_tool_results():
    events = []
    session = SimpleNamespace(
        logger=SimpleNamespace(
            log_context_pruned=lambda reason, pruned, approx_tokens_saved=0: events.append(
                (reason, pruned, approx_tokens_saved)
            )
        )
    )
    messages = [
        {
            "role": "tool",
            "name": "read_file",
            "content": '{"path": "/tmp/app.py", "content": "old content"}',
        },
        {
            "role": "tool",
            "name": "web_search",
            "content": "unrelated",
        },
    ]

    AgentSession._prune_stale_tool_results(
        session,
        messages,
        "edit_file",
        {"path": "/tmp/app.py"},
    )

    assert messages[0]["content"].startswith("[pruned stale read_file")
    assert messages[1]["content"] == "unrelated"
    assert events and events[0][1] == 1
