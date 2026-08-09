from __future__ import annotations

import builtins
from pathlib import Path

from magent import prompt_input


def test_prompt_history_path_is_user_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(prompt_input, "CONFIG_DIR", tmp_path)

    path = prompt_input._history_path("alice", "compose")

    assert path == tmp_path / "prompt-history" / "alice-compose.txt"
    assert path.parent.exists()


def test_rich_multiline_fallback_collects_lines(monkeypatch) -> None:
    lines = iter(["first line", "second line", "/send"])
    monkeypatch.setattr(builtins, "input", lambda: next(lines))

    assert prompt_input._rich_multiline_fallback("alice") == "first line\nsecond line"


def test_rich_multiline_fallback_submits_on_eof(monkeypatch) -> None:
    calls = iter(["only line"])

    def fake_input() -> str:
        try:
            return next(calls)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(builtins, "input", fake_input)

    assert prompt_input._rich_multiline_fallback("alice") == "only line"


def test_rich_multiline_fallback_can_open_editor(monkeypatch) -> None:
    monkeypatch.setattr(builtins, "input", lambda: "/editor")
    monkeypatch.setattr(prompt_input, "_read_editor_prompt", lambda username: f"edited for {username}")

    assert prompt_input._rich_multiline_fallback("alice") == "edited for alice"


def test_editor_prompt_filters_comments(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EDITOR", "test-editor")

    def fake_run(argv, check):
        assert argv[0] == "test-editor"
        Path(argv[1]).write_text("# ignored\nBuild the feature\n\n  # ignored too\nRun tests\n", encoding="utf-8")

    monkeypatch.setattr(prompt_input.subprocess, "run", fake_run)

    assert prompt_input._read_editor_prompt("alice") == "Build the feature\n\nRun tests"


def test_editor_prompt_returns_empty_when_editor_is_missing(monkeypatch) -> None:
    def missing_editor(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(prompt_input.subprocess, "run", missing_editor)

    assert prompt_input._read_editor_prompt("alice") == ""


def test_try_bind_ignores_unsupported_key_sequences() -> None:
    class Bindings:
        def add(self, *keys):
            raise ValueError("unsupported")

    prompt_input._try_bind(Bindings(), ("s-enter",), lambda event: None)
