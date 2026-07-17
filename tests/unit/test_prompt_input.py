from __future__ import annotations

from magent import prompt_input


def test_prompt_history_path_is_user_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(prompt_input, "CONFIG_DIR", tmp_path)

    path = prompt_input._history_path("alice", "compose")

    assert path == tmp_path / "prompt-history" / "alice-compose.txt"
    assert path.parent.exists()
