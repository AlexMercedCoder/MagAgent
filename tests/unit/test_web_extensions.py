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

    assert web_extensions.manage_skill(tmp_path, {"action": "delete", "name": "review"})["removed"]
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
        "transport": "stdio",
        "protocol_mode": "auto",
        "command": "docs-server",
        "args": ["--stdio"],
        "timeout": 30.0,
        "enabled": True,
    }
    assert web_extensions.manage_mcp({"action": "delete", "name": "docs"})["removed"]
    assert len(saved) == 2


def test_extension_names_and_empty_commands_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Names may contain"):
        web_extensions.manage_skill(tmp_path, {"name": "../escape"})
    assert web_extensions.manage_mcp({"name": "empty"})["ok"] is False


def test_remote_mcp_preserves_protocol_auth_references_and_redacts_literals(monkeypatch) -> None:
    config: dict = {"mcp": {"servers": {}}}
    monkeypatch.setattr(web_extensions, "load_global_config", lambda: config)
    monkeypatch.setattr(web_extensions, "save_global_config", lambda _value: None)

    created = web_extensions.manage_mcp(
        {
            "name": "remote",
            "transport": "streamable-http",
            "protocol_mode": "modern",
            "url": "https://mcp.example.test/api",
            "headers": {
                "Authorization": "Bearer ${MCP_TOKEN}",
                "X-Literal": "do-not-return",
            },
            "timeout": 12,
        }
    )

    assert created["ok"] is True
    assert created["server"]["protocol_mode"] == "modern"
    public = web_extensions.public_mcp_config(created["server"])
    assert public["headers"]["Authorization"] == "Bearer ${MCP_TOKEN}"
    assert public["headers"]["X-Literal"] == "[configured]"


def test_legacy_sse_requires_an_explicit_deprecation_acknowledgement(monkeypatch) -> None:
    config: dict = {"mcp": {"servers": {}}}
    monkeypatch.setattr(web_extensions, "load_global_config", lambda: config)
    monkeypatch.setattr(web_extensions, "save_global_config", lambda _value: None)

    rejected = web_extensions.manage_mcp(
        {"name": "old", "transport": "legacy-sse", "url": "https://old.example.test/sse"}
    )
    assert rejected["ok"] is False
    assert "deprecated" in rejected["error"]
