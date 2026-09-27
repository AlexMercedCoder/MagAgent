"""G-3: per-run memory evidence (node ids, scores, token cost, truncation)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from magent.memory import MemoryManager
from magent.memory_evidence import (
    EVIDENCE_SCHEMA,
    RUN_EVIDENCE_SCHEMA,
    build_turn_evidence,
    render_lines,
    run_evidence_payload,
    summarize,
    task_memory_evidence,
)

TURN_KEYS = {
    "schema",
    "turn",
    "recorded_at",
    "status",
    "query_preview",
    "nodes",
    "tokens",
    "truncated",
    "truncation",
}
NODE_KEYS = {"id", "type", "score", "matched", "reason"}
TOKEN_KEYS = {"recalled", "injected", "budget", "profile_reserve"}


def _write_node(root: Path, node_id: str, body: str) -> None:
    (root / f"{node_id}.md").write_text(
        f'---\nid: "{node_id}"\ntype: "preference"\nlinks: []\n---\n# {node_id}\n\n{body}\n',
        encoding="utf-8",
    )


def assert_turn_schema(record: dict) -> None:
    assert set(record) == TURN_KEYS
    assert record["schema"] == EVIDENCE_SCHEMA
    assert set(record["tokens"]) == TOKEN_KEYS
    for node in record["nodes"]:
        assert set(node) == NODE_KEYS
        assert node["score"] is None or isinstance(node["score"], float)


def test_recall_records_node_ids_scores_and_tokens(tmp_path: Path) -> None:
    _write_node(tmp_path, "prefers_pytest", "User prefers pytest for Python projects.")
    mgr = MemoryManager(tmp_path)

    rendered = mgr.recall("pytest")

    evidence = mgr.last_recall_evidence
    assert [node["id"] for node in evidence["nodes"]] == ["prefers_pytest"]
    assert evidence["tokens"] > 0 and evidence["truncated"] is False
    assert evidence["budget_tokens"] == mgr.budget_tokens
    assert rendered


def test_recall_marks_budget_truncation(tmp_path: Path) -> None:
    _write_node(tmp_path, "prefers_pytest", "User prefers pytest. " * 200)
    mgr = MemoryManager(tmp_path, budget_tokens=60, max_node_tokens=400)

    mgr.recall("pytest")

    assert mgr.last_recall_evidence["truncated"] is True


def test_recall_resets_evidence_when_nothing_matches(tmp_path: Path) -> None:
    _write_node(tmp_path, "prefers_pytest", "User prefers pytest.")
    mgr = MemoryManager(tmp_path)
    mgr.recall("pytest")
    assert mgr.last_recall_evidence["nodes"]
    mgr._find_anchor_nodes = lambda *_args, **_kwargs: []  # type: ignore[method-assign]
    assert mgr.recall("anything") == ""
    assert mgr.last_recall_evidence["nodes"] == []


def _context_runtime(monkeypatch, *, memory, profile=None, budget=4000):
    from magent.agent_runtime.context import ContextRuntimeMixin

    runtime = ContextRuntimeMixin()
    runtime.config = SimpleNamespace(
        memory_budget_tokens=budget, repo_map_budget_tokens=0, skill_budget_tokens=0
    )
    runtime.profile = profile
    runtime.memory = memory
    runtime.repo_map = SimpleNamespace(relevant_slice=lambda *_args: "")
    runtime.skill_registry = SimpleNamespace(build_skill_context=lambda *_args, **_kwargs: "")
    runtime.cwd = "."
    runtime.compacted_summary = ""
    runtime.scratchpad = {}
    runtime.turn_count = 3
    logged: list[dict] = []
    runtime.logger = SimpleNamespace(log_activity_event=logged.append)
    monkeypatch.setattr("magent.config_validation.load_ambient_instructions", lambda *_a: "")
    return runtime, logged


def _memory(text: str, nodes: list[dict] | None = None, truncated: bool = False):
    return SimpleNamespace(
        available=True,
        recall=lambda _query: text,
        last_recall_evidence={
            "nodes": nodes or [],
            "tokens": len(text) // 4,
            "budget_tokens": 4000,
            "truncated": truncated,
        },
    )


def test_context_assembly_records_used_memory(monkeypatch) -> None:
    node = {
        "id": "prefers_pytest",
        "type": "preference",
        "score": 0.91,
        "matched": ["body"],
        "reason": "keyword",
    }
    runtime, logged = _context_runtime(monkeypatch, memory=_memory("memory text", [node]))

    runtime._build_context_prompt("Which test runner do I like?")

    record = runtime.last_memory_evidence
    assert_turn_schema(record)
    assert record["status"] == "used"
    assert record["turn"] == 3
    assert record["nodes"] == [node]
    assert record["tokens"]["injected"] > 0 and record["tokens"]["budget"] == 4000
    assert record["truncated"] is False
    assert record["query_preview"] == "Which test runner do I like?"
    assert runtime.memory_evidence == [record]
    assert logged[0]["type"] == "memory_recalled" and logged[0]["detail"] == record


def test_context_assembly_records_profile_truncation(monkeypatch) -> None:
    runtime, _logged = _context_runtime(
        monkeypatch,
        memory=_memory(
            "memory " * 100,
            [{"id": "n", "type": "", "score": None, "matched": [], "reason": ""}],
            truncated=True,
        ),
        profile=SimpleNamespace(max_state_tokens=12),
        budget=20,
    )

    rendered = runtime._build_context_prompt("query")

    record = runtime.last_memory_evidence
    assert "[memory context truncated to reserve profile state]" in rendered
    assert record["truncated"] is True
    assert record["truncation"] == ["recall_budget", "profile_reserve"]
    assert record["tokens"]["budget"] == 8
    assert record["tokens"]["profile_reserve"] == 12


@pytest.mark.parametrize(
    ("memory", "profile", "status"),
    [
        (
            SimpleNamespace(available=True, recall=lambda _q: "", last_recall_evidence={}),
            None,
            "no_match",
        ),
        (SimpleNamespace(available=False), None, "unavailable"),
        (
            SimpleNamespace(available=True, recall=lambda _q: pytest.fail("must not recall")),
            SimpleNamespace(max_state_tokens=0, allows_memory=lambda _action: False),
            "blocked_by_profile",
        ),
    ],
)
def test_context_assembly_records_why_no_memory_was_used(
    monkeypatch, memory, profile, status
) -> None:
    runtime, _logged = _context_runtime(monkeypatch, memory=memory, profile=profile)
    runtime._build_context_prompt("hello")
    record = runtime.last_memory_evidence
    assert_turn_schema(record)
    assert record["status"] == status
    assert record["nodes"] == [] and record["tokens"]["injected"] == 0


def test_evidence_history_is_bounded(monkeypatch) -> None:
    from magent.memory_evidence import MAX_TURNS_PER_RUN

    runtime, _logged = _context_runtime(monkeypatch, memory=SimpleNamespace(available=False))
    for _ in range(MAX_TURNS_PER_RUN + 5):
        runtime._build_context_prompt("x")
    assert len(runtime.memory_evidence) == MAX_TURNS_PER_RUN


def test_long_queries_are_previewed_not_stored_whole() -> None:
    record = build_turn_evidence(turn=1, status="no_match", query="word " * 200)
    assert len(record["query_preview"]) <= 160


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_turn_evidence(turn=1, status="guess")


def _isolated_store(monkeypatch, tmp_path: Path):
    import magent.workbench_store as store_module

    monkeypatch.setattr(store_module, "USERS_DIR", tmp_path / "users")
    return store_module.WorkbenchStore("alex")


def test_run_record_carries_memory_evidence(monkeypatch, tmp_path: Path) -> None:
    from magent.execution_bridge import SessionTaskBridge

    store = _isolated_store(monkeypatch, tmp_path)
    record = build_turn_evidence(
        turn=1,
        status="used",
        query="q",
        recall={
            "nodes": [
                {"id": "a", "type": "fact", "score": 1.0, "matched": ["title"], "reason": "r"}
            ],
            "tokens": 40,
        },
        injected_tokens=40,
        budget_tokens=4000,
    )
    session = SimpleNamespace(
        session_id="s1",
        scratchpad={},
        turn_count=1,
        memory_evidence=[record],
        logger=None,
    )
    bridge = SessionTaskBridge(
        store,
        session,
        kind="ask",
        title="Which runner?",
        project=str(tmp_path),
        permission_policy="balanced",
        provider=SimpleNamespace(provider_id="mock", model="offline-demo"),
    )
    bridge.complete({"ok": True})

    payload = task_memory_evidence("alex", "last")
    assert payload["ok"] is True
    assert payload["schema"] == RUN_EVIDENCE_SCHEMA
    assert payload["task_id"] == bridge.task_id
    assert payload["provider"] == "mock"
    assert payload["turns"] == [record]
    assert payload["summary"] == {
        "turns": 1,
        "turns_with_memory": 1,
        "unique_nodes": ["a"],
        "tokens_injected": 40,
        "truncated": False,
    }
    assert task_memory_evidence("alex", bridge.task_id)["turns"] == [record]
    missing = task_memory_evidence("alex", "task_missing")
    assert missing["ok"] is False and "execution list" in missing["hint"]


def test_desktop_api_exposes_memory_evidence(monkeypatch, tmp_path: Path) -> None:
    from magent import desktop_api

    _isolated_store(monkeypatch, tmp_path)
    empty = desktop_api.memory_evidence("alex")
    assert empty["ok"] is False and empty["schema"] == RUN_EVIDENCE_SCHEMA
    contracts = desktop_api.platform_contracts()["contracts"]
    assert contracts["memory_evidence"]["version"] == RUN_EVIDENCE_SCHEMA


def _slash(cli_main, command: str, session) -> bool:
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return cli_main._handle_slash_command(command, session, None, None, loop)
    finally:
        loop.close()


def test_why_last_explains_the_most_recent_turn(capsys) -> None:
    from magent.cli import main as cli_main

    record = build_turn_evidence(
        turn=2,
        status="used",
        query="q",
        recall={
            "nodes": [
                {
                    "id": "prefers_pytest",
                    "type": "preference",
                    "score": 0.5,
                    "matched": ["body"],
                    "reason": "",
                }
            ],
            "tokens": 30,
            "truncated": True,
        },
        injected_tokens=30,
        budget_tokens=4000,
    )
    session = SimpleNamespace(session_id="s1", memory_evidence=[record])

    assert _slash(cli_main, "/why last", session) is True

    output = capsys.readouterr().out
    assert "prefers_pytest" in output
    assert "score 0.5" in output
    assert "truncated by recall_budget" in output


def test_why_last_without_evidence_points_to_next_step(monkeypatch, tmp_path: Path, capsys) -> None:
    from magent.cli import main as cli_main
    from magent.cli import shared as cli_shared

    _isolated_store(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_shared, "get_current_user", lambda: "alex")
    session = SimpleNamespace(session_id="s1", memory_evidence=[])

    assert _slash(cli_main, "/why last", session) is True
    assert "No recorded run has memory evidence yet" in capsys.readouterr().out


def test_render_lines_and_summary_for_mixed_turns() -> None:
    turns = [
        build_turn_evidence(turn=1, status="no_match"),
        build_turn_evidence(
            turn=2,
            status="used",
            recall={
                "nodes": [{"id": "x", "type": "", "score": None, "matched": [], "reason": ""}],
                "tokens": 5,
            },
            injected_tokens=5,
            budget_tokens=10,
        ),
    ]
    payload = run_evidence_payload(turns, source="session", run_id="run_1")
    lines = render_lines(payload)
    assert "1 of 2 turn(s)" in lines[0]
    assert "no memory matched" in lines[1]
    assert "x (no score; matched graph search)" in lines[-1]
    assert summarize([])["turns"] == 0


def test_web_run_snapshot_includes_memory_evidence() -> None:
    from magent.web_runs import Run

    run = Run("conversation-1")
    record = build_turn_evidence(turn=1, status="no_match")
    run.record_memory("MagAgent", [record])
    snapshot = run.snapshot()
    assert snapshot["memory_evidence"] == [{**record, "speaker": "MagAgent"}]


def test_one_shot_events_include_memory_records() -> None:
    from magent.cli import main as cli_main

    record = build_turn_evidence(turn=1, status="no_match")
    session = SimpleNamespace(scratchpad={}, memory_evidence=[record])
    events = cli_main._one_shot_events("task", "reply", {"ok": True}, session)
    assert {"type": "memory_recalled", "evidence": record} in events
