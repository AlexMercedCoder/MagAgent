"""G-4: `magent auth add <provider> --api-key-stdin`."""

from __future__ import annotations

import json
import stat
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent.cli import main as cli_main
from tests.unit.test_cli import redirect_config

SECRET = "test-key-not-real-0123456789"


@pytest.fixture
def cli(monkeypatch, tmp_path: Path):
    redirect_config(monkeypatch, tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "alex"]).exit_code == 0
    return runner, tmp_path / ".config" / "magent" / "config.toml"


def _json(output: str) -> dict:
    payload, _end = json.JSONDecoder().raw_decode(output[output.index("{") :])
    return payload


def test_stdin_key_is_stored_in_config_without_echo(cli) -> None:
    runner, config_path = cli
    result = runner.invoke(
        cli_main.app,
        ["auth", "add", "nous-portal", "--api-key-stdin", "--storage", "config", "--json"],
        input=SECRET + "\n",
    )
    assert result.exit_code == 0, result.output
    assert SECRET not in result.output
    payload = _json(result.output)
    assert payload == {
        "ok": True,
        "provider": "nous-portal",
        "storage": "config",
        "config_path": str(config_path),
        "source": "stdin",
    }
    saved = tomllib.loads(config_path.read_text())
    assert saved["providers"]["nous-portal"]["api_key"] == SECRET
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_stdin_key_goes_to_keyring_when_available(cli, monkeypatch) -> None:
    runner, config_path = cli
    stored: dict[str, str] = {}
    import magent.auth_store as auth_store

    monkeypatch.setattr(auth_store, "keyring_available", lambda: True)
    monkeypatch.setattr(
        auth_store,
        "save_keyring_secret",
        lambda provider, value: (
            stored.update({provider: value})
            or {"ok": True, "provider": provider, "storage": "keyring"}
        ),
    )
    result = runner.invoke(cli_main.app, ["auth", "add", "nous", "--api-key-stdin"], input=SECRET)
    assert result.exit_code == 0, result.output
    payload = _json(result.output)
    assert payload["provider"] == "nous-portal"  # alias canonicalized
    assert payload["account"] == "provider:nous-portal"
    assert stored == {"nous-portal": SECRET}
    saved = tomllib.loads(config_path.read_text())
    assert saved["providers"]["nous-portal"] == {"api_key_keyring": "provider:nous-portal"}


def test_missing_keyring_explains_the_config_option(cli, monkeypatch) -> None:
    runner, _config = cli
    monkeypatch.setattr("magent.auth_store.keyring_available", lambda: False)
    result = runner.invoke(cli_main.app, ["auth", "add", "openai", "--api-key-stdin"], input=SECRET)
    assert result.exit_code == 1
    payload = _json(result.output)
    assert "--storage config" in payload["hint"]
    assert SECRET not in result.output


@pytest.mark.parametrize(
    ("args", "stdin", "message"),
    [
        (["auth", "add", "openai", "--api-key-stdin"], "", "No key was received"),
        (["auth", "add", "openai", "--api-key-stdin"], "   \n", "No key was received"),
        (["auth", "add", "nope-provider", "--api-key-stdin"], SECRET, "Unknown provider"),
        (["auth", "add", "ollama", "--api-key-stdin"], SECRET, "does not use an API key"),
        (["auth", "add", "mock", "--api-key-stdin"], SECRET, "does not use an API key"),
        (["auth", "add", "openai", "--api-key-stdin", "--storage", "vault"], SECRET, "--storage"),
        (
            ["auth", "add", "openai", "--api-key-stdin", "--api-key", "x"],
            SECRET,
            "not both",
        ),
    ],
)
def test_usage_errors_exit_2_with_guidance(cli, args, stdin, message) -> None:
    runner, _config = cli
    result = runner.invoke(cli_main.app, args, input=stdin)
    assert result.exit_code == 2, result.output
    assert message in _json(result.output)["error"]
    assert SECRET not in result.output


def test_terminal_stdin_is_refused(cli, monkeypatch) -> None:
    runner, _config = cli

    class Tty:
        def isatty(self) -> bool:
            return True

        def read(self) -> str:  # pragma: no cover - must not be read
            raise AssertionError("must not read a terminal")

    monkeypatch.setattr(cli_main.sys, "stdin", Tty())
    from magent.cli.main import auth_add_cmd

    with pytest.raises(Exception) as raised:
        auth_add_cmd("openai", api_key_stdin=True, storage="config", api_key="", json_output=False)
    assert getattr(raised.value, "exit_code", None) == 2


def test_no_key_and_no_terminal_points_to_stdin_flag(cli) -> None:
    runner, _config = cli
    result = runner.invoke(cli_main.app, ["auth", "add", "openai"], input="")
    assert result.exit_code == 2
    assert "--api-key-stdin" in _json(result.output)["hint"]


def test_argv_key_still_works_but_warns(cli) -> None:
    runner, _config = cli
    result = runner.invoke(
        cli_main.app,
        ["auth", "add", "openai", "--api-key", SECRET, "--storage", "config"],
    )
    assert result.exit_code == 0
    assert "use --api-key-stdin instead" in result.output
    assert _json(result.output)["source"] == "argv"


def test_remove_clears_a_config_stored_key(cli) -> None:
    runner, config_path = cli
    runner.invoke(
        cli_main.app,
        ["auth", "add", "openai", "--api-key-stdin", "--storage", "config"],
        input=SECRET,
    )
    result = runner.invoke(cli_main.app, ["auth", "remove", "openai"])
    assert result.exit_code == 0, result.output
    assert _json(result.output)["removed_from_config"] is True
    assert "api_key" not in tomllib.loads(config_path.read_text())["providers"]["openai"]
