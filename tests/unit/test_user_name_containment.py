"""G-15: user names cannot leave USERS_DIR.

User and profile names were joined onto USERS_DIR unchecked, so
`magent user delete ../.. --yes` removed ~/.config. Every test here points
USERS_DIR at a throwaway tree under tmp_path (never the real home), with a
sentinel file where a traversal would land.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent import config as magent_config


@pytest.fixture
def users(tmp_path: Path, monkeypatch) -> Path:
    real_home = os.environ.get("MAGENT_TEST_REAL_HOME") == "1"
    assert not real_home, "these tests must never run against a real home directory"
    outside = tmp_path / "outside"
    users_dir = outside / "config" / "users"
    users_dir.mkdir(parents=True)
    (outside / "sentinel.txt").write_text("keep me\n", encoding="utf-8")
    (outside / "config" / "keep.toml").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(magent_config, "USERS_DIR", users_dir)
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", users_dir / "current")
    return users_dir


def _intact(users_dir: Path) -> None:
    assert (users_dir.parent.parent / "sentinel.txt").exists()
    assert (users_dir.parent / "keep.toml").exists()


@pytest.mark.parametrize("name", ["../..", "..", "../evil", "a/b", "/etc", ".hidden", "current"])
def test_library_functions_refuse_unsafe_names(users: Path, name: str) -> None:
    with pytest.raises(magent_config.InvalidUserNameError):
        magent_config.delete_user(name)
    with pytest.raises(magent_config.InvalidUserNameError):
        magent_config.create_user(name)
    with pytest.raises(magent_config.InvalidUserNameError):
        magent_config.set_current_user(name)
    with pytest.raises(magent_config.InvalidUserNameError):
        magent_config.user_exists(name)
    with pytest.raises(magent_config.InvalidUserNameError):
        magent_config.user_memory_dir(name)
    _intact(users)
    assert not (users.parent / "evil").exists()


def test_cli_user_delete_cannot_traverse(users: Path) -> None:
    from magent.cli import main as cli_main

    result = CliRunner().invoke(cli_main.app, ["user", "delete", "../..", "--yes"])
    assert result.exit_code == 2, result.output
    assert "Invalid user name" in result.output
    _intact(users)


def test_cli_user_create_cannot_traverse(users: Path) -> None:
    from magent.cli import main as cli_main

    result = CliRunner().invoke(cli_main.app, ["user", "create", "../evil"])
    assert result.exit_code == 2, result.output
    assert not (users.parent / "evil").exists()


def test_a_user_directory_symlinked_out_of_users_dir_is_refused(users: Path) -> None:
    target = users.parent.parent / "elsewhere"
    target.mkdir()
    (target / "data.txt").write_text("precious\n", encoding="utf-8")
    (users / "linked").symlink_to(target, target_is_directory=True)
    with pytest.raises(magent_config.InvalidUserNameError):
        magent_config.delete_user("linked")
    assert (target / "data.txt").exists()


def test_invalid_stored_current_user_is_refused_with_a_hint(users: Path) -> None:
    from magent.cli import main as cli_main

    (users / "current").write_text("../..", encoding="utf-8")
    with pytest.raises(magent_config.InvalidUserNameError, match="magent user switch"):
        magent_config.get_current_user()

    runner = CliRunner()
    refused = runner.invoke(cli_main.app, ["memory", "stats"])
    assert refused.exit_code == 2, refused.output
    assert "magent user switch" in refused.output

    magent_config.create_user("alex")
    assert runner.invoke(cli_main.app, ["user", "switch", "alex"]).exit_code == 0
    assert magent_config.get_current_user() == "alex"
    _intact(users)


def test_other_modules_contain_their_user_joins(users: Path, monkeypatch) -> None:
    from magent import desktop_api, workbench_store
    from magent.team_memory import TeamMemory

    monkeypatch.setattr(workbench_store, "USERS_DIR", users)
    monkeypatch.setattr(desktop_api, "USERS_DIR", users)
    with pytest.raises(ValueError):
        workbench_store.WorkbenchStore("../..")
    with pytest.raises(ValueError):
        TeamMemory("../x")
    with pytest.raises(ValueError):
        desktop_api.execution_tasks("../..")
    assert not (users.parent / "workbench").exists()
    assert not (users.parent.parent / "workbench").exists()
    _intact(users)


def test_ordinary_names_still_work(users: Path) -> None:
    for name in ("alex", "Alex.Merced", "team-1", "a_b"):
        magent_config.create_user(name)
        assert magent_config.user_exists(name)
    magent_config.set_current_user("alex")
    assert magent_config.get_current_user() == "alex"
    magent_config.delete_user("team-1")
    assert not magent_config.user_exists("team-1")
