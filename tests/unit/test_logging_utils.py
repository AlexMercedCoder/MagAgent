from __future__ import annotations

import json

from magent import logging as magent_logging
from magent.logging import SessionLogger, list_session_logs
from magent.utils import human_bytes


def test_human_bytes_formats_units() -> None:
    assert human_bytes(12) == "12.0 B"
    assert human_bytes(2048) == "2.0 KB"
    assert human_bytes(3 * 1024 * 1024) == "3.0 MB"


def test_session_logger_writes_and_lists_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(magent_logging, "LOGS_DIR", tmp_path / "logs")

    logger = SessionLogger("sess1", "alice")
    logger.log_session_start("openai", "gpt", "/repo")
    logger.log_user_turn(1, "x" * 600)
    logger.log_assistant_turn(1, "response", tool_calls=2)
    logger.log_tool_call("read_file", {"path": "a" * 150}, True, 0)
    logger.log_memory_write(2, "demo")
    logger.log_token_usage("openai", "gpt", prompt_tokens=10, completion_tokens=5)
    logger.log_context_pruned("stale", 3, approx_tokens_saved=120)
    logger.log_session_end(1)

    lines = logger.path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    listed = list_session_logs()

    assert [record["event"] for record in records] == [
        "session_start",
        "user_turn",
        "assistant_turn",
        "tool_call",
        "memory_write",
        "token_usage",
        "context_pruned",
        "session_end",
    ]
    assert len(records[1]["message"]) == 500
    assert len(records[3]["args"]["path"]) == 100
    assert records[5]["total_tokens"] == 15
    assert listed[0]["session"] == "sess1"
    assert listed[0]["ended"] != "active"
    assert listed[0]["events"] == 8


def test_list_session_logs_handles_missing_and_active_logs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(magent_logging, "LOGS_DIR", tmp_path / "logs")

    assert list_session_logs() == []

    logger = SessionLogger("active", "alice")
    logger.log_session_start("ollama", "qwen", "/repo")
    logger.close()

    listed = list_session_logs()

    assert listed[0]["session"] == "active"
    assert listed[0]["ended"] == "active"
