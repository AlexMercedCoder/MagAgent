from __future__ import annotations

from pathlib import Path

import pytest

from magent import web_extensions


def test_project_skill_lifecycle_is_confined_to_workspace(tmp_path: Path) -> None:
    saved = web_extensions.manage_skill(
        tmp_path,
        {"action": "save", "name": "review", "description": "Review code", "body": "Check tests."},
    )
    path = Path(saved["path"])
    assert path.is_relative_to(tmp_path)
    assert "Check tests." in path.read_text(encoding="utf-8")

    assert web_extensions.manage_skill(tmp_path, {"action": "delete", "name": "review"})[
        "removed"
    ]
    assert not path.exists()


def test_mcp_lifecycle_preserves_only_reviewed_fields(monkeypatch) -> None:
    config: dict = {"mcp": {"servers": {}}}
    saved: list[dict] = []
    monkeypatch.setattr(web_extensions, "load_global_config", lambda: config)
    monkeypatch.setattr(web_extensions, "save_global_config", lambda value: saved.append(value))

    created = web_extensions.manage_mcp(
        {"name": "docs", "command": "docs-server", "args": ["--stdio"], "enabled": True}
    )
    assert created["server"] == {
        "command": "docs-server",
        "args": ["--stdio"],
        "enabled": True,
    }
    assert web_extensions.manage_mcp({"action": "delete", "name": "docs"})["removed"]
    assert len(saved) == 2


def test_extension_names_and_empty_commands_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Names may contain"):
        web_extensions.manage_skill(tmp_path, {"name": "../escape"})
    assert web_extensions.manage_mcp({"name": "empty"})["ok"] is False
