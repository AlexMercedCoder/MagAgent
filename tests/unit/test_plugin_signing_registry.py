"""Phase 6: signed plugin trust and static registries."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent.cli import main as cli_main
from magent.plugin_registry import (
    RegistryError,
    add_registry,
    build_registry,
    install_from_registry,
    search,
)
from magent.plugin_signing import (
    generate_key,
    list_trusted_keys,
    sign_plugin,
    trust_key,
    verify_signature,
)
from tests.unit.test_plugin_sdk import make_plugin, redirect_plugins

runner = CliRunner()


@pytest.fixture
def env(monkeypatch, tmp_path: Path) -> Path:
    redirect_plugins(monkeypatch, tmp_path)
    return tmp_path


def test_sign_verify_and_tamper_detection(env: Path) -> None:
    plugin = make_plugin(env / "demo")
    key = generate_key(env / "keys" / "acme.pem")
    assert (env / "keys" / "acme.pem").stat().st_mode & 0o777 == 0o600
    assert verify_signature(plugin)["status"] == "unsigned"
    sign_plugin(plugin, env / "keys" / "acme.pem", key_id="acme")
    assert verify_signature(plugin)["status"] == "untrusted"
    trust_key("acme", key["public_key"])
    verified = verify_signature(plugin)
    assert verified["status"] == "trusted" and verified["trusted_as"] == "acme"
    assert verified["fingerprint"] == key["fingerprint"]

    (plugin / "skills" / "demo" / "SKILL.md").write_text("# Changed\n", encoding="utf-8")
    assert verify_signature(plugin)["reason"] == "plugin files changed"
    (plugin / "skills" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    manifest = plugin / "magent-plugin.toml"
    manifest.write_text(manifest.read_text().replace("permissions = []", 'permissions = ["shell"]'))
    assert verify_signature(plugin)["reason"] == "manifest changed"


def test_forged_signature_is_invalid(env: Path) -> None:
    plugin = make_plugin(env / "demo")
    generate_key(env / "a.pem")
    other = generate_key(env / "b.pem")
    sign_plugin(plugin, env / "a.pem", key_id="a")
    document = json.loads((plugin / "magent-plugin.sig").read_text())
    document["public_key"] = other["public_key"]  # claim someone else signed it
    (plugin / "magent-plugin.sig").write_text(json.dumps(document))
    result = verify_signature(plugin)
    assert result["status"] == "invalid" and "does not verify" in result["reason"]


def test_keys_are_never_overwritten(env: Path) -> None:
    generate_key(env / "k.pem")
    with pytest.raises(FileExistsError):
        generate_key(env / "k.pem")


def _registry(env: Path, *, signed: bool = True) -> tuple[Path, dict]:
    (env / "source").mkdir(exist_ok=True)
    plugin = make_plugin(env / "source" / "demo")
    key = generate_key(env / "publisher.pem")
    build_registry(
        [plugin],
        env / "registry",
        name="acme",
        sign_key=env / "publisher.pem" if signed else None,
        key_id="acme",
    )
    add_registry("acme", str(env / "registry" / "index.json"))
    return plugin, key


def test_registry_search_and_trusted_install(env: Path) -> None:
    _plugin, key = _registry(env)
    [found] = search("demo")
    assert found["registry"] == "acme" and found["signature"]["key_id"] == "acme"

    with pytest.raises(RegistryError, match="do not trust"):
        install_from_registry("demo")
    asked = []

    def confirm(entry, verification):
        asked.append(verification["fingerprint"])
        return True

    result = install_from_registry("demo@1.0.0", confirm_key=confirm)
    assert result["ok"] is True and result["signature"]["status"] == "trusted"
    assert asked == [key["fingerprint"]]
    assert [item["key_id"] for item in list_trusted_keys()] == ["acme"]


def test_unsigned_and_tampered_archives_are_refused(env: Path) -> None:
    _registry(env, signed=False)
    with pytest.raises(RegistryError, match="not signed"):
        install_from_registry("demo")
    assert install_from_registry("demo", allow_unsigned=True)["ok"] is True

    archive = env / "registry" / "demo-1.0.0.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(RegistryError, match="sha256"):
        install_from_registry("demo", allow_unsigned=True, force=True)


def test_archives_cannot_escape(env: Path, tmp_path: Path) -> None:
    from magent.plugin_registry import _safe_extract

    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("x")
    with tarfile.open(evil, "w:gz") as bundle:
        bundle.add(payload, arcname="../../escape.txt")
    target = tmp_path / "out"
    target.mkdir()
    with pytest.raises(RegistryError, match="escapes"):
        _safe_extract(evil.read_bytes(), target)


def test_cli_flow(env: Path) -> None:
    keygen = runner.invoke(cli_main.app, ["plugin", "keygen", str(env / "me.pem")])
    assert keygen.exit_code == 0, keygen.output
    public_key = json.loads(keygen.output[: keygen.output.rindex("}") + 1])["public_key"]
    plugin = make_plugin(env / "demo")
    signed = runner.invoke(
        cli_main.app,
        ["plugin", "sign", str(plugin), "--key", str(env / "me.pem"), "--key-id", "me"],
    )
    assert signed.exit_code == 0, signed.output
    strict = runner.invoke(cli_main.app, ["plugin", "verify", str(plugin), "--require-signature"])
    assert strict.exit_code == 1
    assert runner.invoke(cli_main.app, ["plugin", "trust", "add", "me", public_key]).exit_code == 0
    ok = runner.invoke(cli_main.app, ["plugin", "verify", str(plugin), "--require-signature"])
    assert ok.exit_code == 0, ok.output
    built = runner.invoke(
        cli_main.app,
        ["plugin", "registry", "build", str(plugin), "--out", str(env / "reg"), "--name", "mine"],
    )
    assert built.exit_code == 0, built.output
    assert (
        runner.invoke(
            cli_main.app, ["plugin", "registry", "add", "mine", str(env / "reg")]
        ).exit_code
        == 0
    )
    listed = runner.invoke(cli_main.app, ["plugin", "search", "demo"])
    assert "demo" in listed.output and "me" in listed.output
    installed = runner.invoke(cli_main.app, ["plugin", "install", "demo", "--registry", "mine"])
    assert installed.exit_code == 0, installed.output
    missing = runner.invoke(cli_main.app, ["plugin", "install", "nope"])
    assert missing.exit_code == 1 and "No plugin" in missing.output
