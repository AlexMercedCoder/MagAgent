from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from magent.web_workspace import WorkspaceError, WorkspaceService, extension_inventory


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_workspace_listing_preview_upload_and_context_are_bounded(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".magent").mkdir()
    (tmp_path / ".magent" / "secret.json").write_text("secret", encoding="utf-8")
    service = WorkspaceService(tmp_path)

    listing = service.list_files()
    assert [item["path"] for item in listing["files"]] == ["src/app.py"]
    assert service.preview("src/app.py")["content"] == "print('ok')\n"

    uploaded = service.upload("../note.txt", base64.b64encode(b"hello").decode(), "chat/id")
    path = uploaded["file"]["path"]
    assert path == ".magent/attachments/chat_id/note.txt"
    prompt, refs = service.context_prompt(["src/app.py", path])
    assert "print('ok')" in prompt
    assert [item["path"] for item in refs] == ["src/app.py", path]

    with pytest.raises(WorkspaceError, match="escapes"):
        service.preview("../outside.txt")
    with pytest.raises(WorkspaceError, match="internal state"):
        service.preview(".magent/secret.json")
    with pytest.raises(WorkspaceError, match="no more than"):
        service.context_prompt(["src/app.py"] * 21)


def test_binary_preview_is_not_treated_as_text(tmp_path: Path) -> None:
    (tmp_path / "pixel.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    result = WorkspaceService(tmp_path).preview("pixel.png")
    assert result["text"] is False
    assert result["data_url"].startswith("data:image/png;base64,")


def test_git_status_diff_and_staging_are_project_confined(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "start")
    (tmp_path / "tracked.txt").write_text("two\n", encoding="utf-8")
    service = WorkspaceService(tmp_path)

    assert any("tracked.txt" in line for line in service.git()["status"])
    assert "+two" in service.diff()["diff"]
    assert service.git_action("stage", "tracked.txt")["ok"] is True
    assert "+two" in service.diff(staged=True)["diff"]
    assert service.git_action("unstage", "tracked.txt")["ok"] is True
    assert service.git_action("discard", "tracked.txt")["ok"] is True
    assert (tmp_path / "tracked.txt").read_text() == "one\n"


def test_terminal_uses_argv_without_shell_expansion(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    result = service.terminal("printf 'hello $HOME'")
    assert result["ok"] is True
    assert result["stdout"] == "hello $HOME"
    assert service.terminal("definitely-not-a-real-command")["returncode"] == 127


def test_extension_inventory_redacts_plugin_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "magent.plugins.list_plugins",
        lambda: {
            "plugins": [
                {
                    "name": "demo",
                    "version": "1.0",
                    "enabled": True,
                    "integrity": "verified",
                    "valid": True,
                    "metadata": {"token": "must-not-leak"},
                    "grants": {"secret-project": ["shell"]},
                    "path": "/private/plugin",
                }
            ]
        },
    )

    result = extension_inventory(None, tmp_path)

    assert result["plugins"] == [
        {
            "name": "demo",
            "version": "1.0",
            "enabled": True,
            "integrity": "verified",
            "valid": True,
        }
    ]
    assert "must-not-leak" not in str(result)
