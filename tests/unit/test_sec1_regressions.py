"""SEC-1: regression tests for the security self-review of the 1.4.0 branch.

Each test here failed before its fix (see docs threat model, "SEC-1 findings").
They are grouped by surface: RPC gateway, approval doorbells, team memory,
plugin signing and registries, graph executors, --prompt-file, parallel read
tools, grants and `auth add`.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from magent import rpc_gateway
from magent.rpc_gateway import FORBIDDEN, UNAUTHORIZED, Gateway, serve_rpc
from tests.unit.test_rpc_gateway import AUTH, TOKEN, call, fake_command

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------- RPC gateway


@pytest.fixture
def gateway(tmp_path: Path):
    gw = Gateway(
        token=TOKEN, roots=[tmp_path], audit_path=tmp_path / "audit.jsonl", command=fake_command
    )
    yield gw
    gw.shutdown()


@pytest.mark.parametrize(
    "args",
    [
        ["--provider", "x", "serve", "--rpc", "--host", "0.0.0.0", "--allow-remote"],
        ["-p", "openai", "ui"],
        ["-m", "gpt", "daemon", "start"],
        ["--install-completion"],
        ["--show-completion=bash"],
    ],
)
def test_denied_commands_cannot_hide_behind_root_options(gateway: Gateway, args) -> None:
    # Root options that take a value made the value look like the command
    # word, so `--provider x serve` slipped past the `serve` denial.
    response = call(gateway, "run_magent", {"args": args})
    assert response.get("error", {}).get("code") == FORBIDDEN, response


def test_finished_streams_are_forgotten(tmp_path: Path) -> None:
    gateway = Gateway(token=TOKEN, roots=[tmp_path], rate_per_minute=100_000, command=fake_command)
    for index in range(40):
        started = call(gateway, "stream.start", {"args": ["status"], "id": f"s{index}"})
        assert "result" in started, started
        stream = started["result"]
        deadline, after, done = time.monotonic() + 30, 0, False
        while not done:
            page = call(
                gateway, "stream.events", {"id": stream["id"], "after": after, "wait_ms": 500}
            )
            after, done = page["result"]["next"], page["result"]["done"]
            assert time.monotonic() < deadline
    assert len(gateway.streams) <= 32
    gateway.shutdown()


def test_unauthenticated_floods_do_not_fill_the_audit_log(gateway: Gateway, tmp_path: Path) -> None:
    for _ in range(200):
        assert call(gateway, "runtime_info", auth="Bearer nope")["error"]["code"] == UNAUTHORIZED
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 60


def test_audit_log_is_owner_only(gateway: Gateway, tmp_path: Path) -> None:
    call(gateway, "runtime_info")
    assert (tmp_path / "audit.jsonl").stat().st_mode & 0o077 == 0


@pytest.fixture
def http_gateway(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rpc_gateway, "SOCKET_TIMEOUT_SECONDS", 1, raising=False)
    server, gateway, info = serve_rpc(port=0, token=TOKEN, roots=[tmp_path])
    yield info
    server.shutdown()
    server.server_close()
    gateway.shutdown()


def test_idle_connections_are_dropped(http_gateway: dict) -> None:
    # One thread per connection and no socket timeout: anyone who could reach
    # the port could hold threads open forever without a token.
    with socket.create_connection(("127.0.0.1", http_gateway["port"]), timeout=10) as sock:
        sock.sendall(b"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100\r\n\r\n")
        started = time.monotonic()
        assert sock.recv(1024) == b""  # closed by the server, not by our timeout
        assert time.monotonic() - started < 9


def _post(info: dict, headers: dict[str, str], body: bytes = b"") -> int:
    request = urllib.request.Request(info["url"], data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_browser_requests_are_refused_even_with_the_token(http_gateway: dict) -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "runtime_info"}).encode()
    headers = {"Authorization": AUTH, "Content-Type": "application/json"}
    assert _post(http_gateway, headers, body) == 200
    assert _post(http_gateway, {**headers, "Origin": "http://evil.example"}, body) == 403


def test_malformed_content_length_gets_an_answer(http_gateway: dict) -> None:
    with socket.create_connection(("127.0.0.1", http_gateway["port"]), timeout=10) as sock:
        sock.sendall(b"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: abc\r\n\r\n")
        assert sock.recv(1024).startswith(b"HTTP/1.1 400")


# ------------------------------------------------------- approval doorbells


def test_doorbells_refuse_a_socket_directory_someone_else_prepared(monkeypatch) -> None:
    import shutil
    import tempfile

    from magent import approval_bus

    # A short base: a Unix socket path must fit in ~108 bytes.
    base = Path(tempfile.mkdtemp(prefix="sec1-"))
    try:
        monkeypatch.setattr(approval_bus.tempfile, "gettempdir", lambda: str(base))
        attacker = base / "attacker"
        attacker.mkdir()
        (base / f"magent-doorbells-{os.getuid()}").symlink_to(attacker)
        doorbell = approval_bus.Doorbell()
        try:
            assert not list(attacker.iterdir())
            assert doorbell.family == "udp"
        finally:
            doorbell.close()
    finally:
        shutil.rmtree(base, ignore_errors=True)


# -------------------------------------------------------------- team memory


@pytest.fixture
def team(tmp_path: Path):
    from magent.team_memory import TeamMemory

    remote = tmp_path / "shared" / "team.git"
    alice = TeamMemory("alice", root=tmp_path / "alice" / "team")
    alice.init(str(remote), create=True)
    bob = TeamMemory("bob", root=tmp_path / "bob" / "team")
    bob.init(str(remote.resolve()))
    return alice, bob, tmp_path


def _raw_git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=mallory", "-c", "user.email=m@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_sync_refuses_symlinks_pushed_straight_to_main(team) -> None:
    from magent.team_memory import TeamMemoryError

    alice, bob, tmp = team
    secret = tmp / "secret.txt"
    secret.write_text("ssh private key material\n", encoding="utf-8")
    rogue = tmp / "rogue"
    _raw_git("clone", str(tmp / "shared" / "team.git"), str(rogue), cwd=tmp)
    (rogue / "nodes" / "leak.md").symlink_to(secret)
    _raw_git("add", "-A", cwd=rogue)
    _raw_git("commit", "-m", "direct push", cwd=rogue)
    _raw_git("push", "origin", "HEAD:main", cwd=rogue)

    with pytest.raises(TeamMemoryError, match="not a regular file"):
        bob.sync()
    assert not (bob.nodes_dir / "leak.md").exists()


def test_forged_author_trailer_does_not_allow_self_review(team) -> None:
    from magent.team_memory import TeamMemoryError

    alice, _bob, _tmp = team
    alice._git("fetch", "origin")
    alice._git("checkout", "-B", "proposals/alice/forged01", "origin/main")
    (alice.nodes_dir / "tip.md").write_text(
        '---\nid: "tip"\ntype: "preference"\nlinks: []\n---\n# tip\n\nUse tabs.\n',
        encoding="utf-8",
    )
    alice._git("add", "nodes")
    alice._git(
        "commit", "-m", "Tip\n\nMagent-Proposal: forged01\nMagent-Author: bob\nMagent-Nodes: tip\n"
    )
    alice._git("push", "-u", "origin", "proposals/alice/forged01")
    alice._git("checkout", "main")

    with pytest.raises(TeamMemoryError):
        alice.decide("forged01", decision="accept")


def test_team_recall_is_skipped_when_the_clone_holds_a_symlink(tmp_path: Path) -> None:
    from magent.agent import _team_memory_manager
    from magent.team_memory import TeamMemory

    team = TeamMemory("carol")
    team.init(str(tmp_path / "team.git"), create=True)
    (team.nodes_dir / "leak.md").symlink_to(tmp_path / "anything.md")
    config = SimpleNamespace(
        get=lambda *_args, default=None: {}, memory_budget_tokens=4000, recall_body_tokens=200
    )
    assert _team_memory_manager(config, "carol", None) is None


# ------------------------------------------------- plugin signing / registry


@pytest.fixture
def plugin_env(monkeypatch, tmp_path: Path) -> Path:
    from tests.unit.test_plugin_sdk import redirect_plugins

    redirect_plugins(monkeypatch, tmp_path)
    return tmp_path


def _pack(root: Path, *, name: str = "demo", version: str = "1.0.0", permissions=()) -> Path:
    from tests.unit.test_plugin_sdk import make_plugin

    root.parent.mkdir(parents=True, exist_ok=True)
    make_plugin(root)
    manifest = (root / "magent-plugin.toml").read_text(encoding="utf-8")
    manifest = manifest.replace('name = "demo"', f'name = "{name}"')
    manifest = manifest.replace('version = "1.0.0"', f'version = "{version}"')
    manifest = manifest.replace(
        "permissions = []", f"permissions = {json.dumps(list(permissions))}"
    )
    (root / "magent-plugin.toml").write_text(manifest, encoding="utf-8")
    return root


def _publish(env: Path, packs: list[Path], registry: str = "acme") -> dict:
    from magent.plugin_registry import add_registry, build_registry
    from magent.plugin_signing import generate_key

    key_path = env / f"{registry}.pem"
    key = generate_key(key_path) if not key_path.exists() else None
    build_registry(packs, env / registry, name=registry, sign_key=key_path, key_id=registry)
    add_registry(registry, str(env / registry / "index.json"))
    return key or {}


def test_installed_signed_plugins_still_verify(plugin_env: Path) -> None:
    from magent.plugin_registry import install_from_registry
    from magent.plugin_signing import verify_signature
    from magent.plugins import set_plugin_enabled

    _publish(plugin_env, [_pack(plugin_env / "src" / "demo")])
    result = install_from_registry("demo", confirm_key=lambda *_: True)
    assert verify_signature(Path(result["path"]))["status"] == "trusted"
    assert set_plugin_enabled("demo", True)["ok"] is True


def test_nested_manifest_named_files_are_covered_by_the_signature(plugin_env: Path) -> None:
    from magent.plugin_signing import generate_key, sign_plugin, trust_key, verify_signature

    plugin = _pack(plugin_env / "demo")
    key = generate_key(plugin_env / "k.pem")
    trust_key("me", key["public_key"])
    sign_plugin(plugin, plugin_env / "k.pem", key_id="me")
    assert verify_signature(plugin)["status"] == "trusted"
    (plugin / "skills" / "magent-plugin.toml").write_text("added after signing\n")
    assert verify_signature(plugin)["status"] == "invalid"


def test_symlinked_directories_cannot_add_unsigned_content(plugin_env: Path) -> None:
    from magent.plugin_signing import generate_key, sign_plugin, trust_key, verify_signature

    plugin = _pack(plugin_env / "demo")
    key = generate_key(plugin_env / "k.pem")
    trust_key("me", key["public_key"])
    sign_plugin(plugin, plugin_env / "k.pem", key_id="me")
    outside = plugin_env / "outside"
    outside.mkdir()
    (outside / "hook.py").write_text("import os\n")
    (plugin / "extra").symlink_to(outside, target_is_directory=True)
    assert verify_signature(plugin)["status"] == "invalid"


def test_newest_version_is_chosen_numerically(plugin_env: Path) -> None:
    from magent.plugin_registry import install_from_registry

    _publish(
        plugin_env,
        [
            _pack(plugin_env / "v9" / "demo", version="1.9.0"),
            _pack(plugin_env / "v10" / "demo", version="1.10.0"),
        ],
    )
    result = install_from_registry("demo", confirm_key=lambda *_: True)
    assert result["version"] == "1.10.0"


def test_a_second_registry_cannot_shadow_a_plugin(plugin_env: Path) -> None:
    from magent.plugin_registry import RegistryError, install_from_registry

    _publish(plugin_env, [_pack(plugin_env / "a" / "demo")], registry="acme")
    _publish(plugin_env, [_pack(plugin_env / "b" / "demo", version="9.0.0")], registry="shadow")
    with pytest.raises(RegistryError, match="more than one registry"):
        install_from_registry("demo", confirm_key=lambda *_: True)
    assert install_from_registry("demo", registry="acme", confirm_key=lambda *_: True)["ok"]


def test_trust_prompt_shows_the_signed_manifest_permissions(plugin_env: Path) -> None:
    from magent.plugin_registry import install_from_registry

    _publish(plugin_env, [_pack(plugin_env / "src" / "demo", permissions=["shell"])])
    index_path = plugin_env / "acme" / "index.json"
    index = json.loads(index_path.read_text())
    index["plugins"][0]["permissions"] = []  # the unsigned index lies
    index_path.write_text(json.dumps(index))
    seen = []

    def confirm(entry, verification):
        seen.append(verification.get("permissions"))
        return False

    with pytest.raises(Exception, match="do not trust"):
        install_from_registry("demo", confirm_key=confirm)
    assert seen == [["shell"]]


def test_a_new_key_cannot_replace_a_trusted_key_id(plugin_env: Path) -> None:
    from magent.plugin_signing import generate_key, list_trusted_keys, trust_key

    first = generate_key(plugin_env / "a.pem")
    second = generate_key(plugin_env / "b.pem")
    trust_key("acme", first["public_key"])
    with pytest.raises(ValueError, match="already trusted"):
        trust_key("acme", second["public_key"])
    [row] = list_trusted_keys()
    assert row["public_key"] == first["public_key"]


def test_archive_must_hold_the_plugin_the_index_names(plugin_env: Path) -> None:
    from magent.plugin_registry import RegistryError, install_from_registry

    _publish(plugin_env, [_pack(plugin_env / "src" / "other", name="other")])
    index_path = plugin_env / "acme" / "index.json"
    index = json.loads(index_path.read_text())
    index["plugins"][0]["name"] = "demo"
    index_path.write_text(json.dumps(index))
    with pytest.raises(RegistryError, match="not demo"):
        install_from_registry("demo", confirm_key=lambda *_: True)


def test_archives_that_expand_too_far_are_refused(tmp_path: Path, monkeypatch) -> None:
    from magent import plugin_registry
    from magent.plugin_registry import RegistryError, _safe_extract

    monkeypatch.setattr(plugin_registry, "MAX_UNPACKED_BYTES", 1000, raising=False)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        data = b"0" * 5000
        info = tarfile.TarInfo("demo/magent-plugin.toml")
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))
    target = tmp_path / "out"
    target.mkdir()
    with pytest.raises(RegistryError, match="unpacks to more than"):
        _safe_extract(buffer.getvalue(), target)


def test_registry_redirects_may_not_downgrade_to_plain_http(plugin_env: Path) -> None:
    from magent.plugin_registry import RegistryError, fetch_index

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", "http://registry.example.invalid/index.json")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(RegistryError, match="HTTPS"):
            fetch_index(f"http://127.0.0.1:{server.server_address[1]}/index.json")
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------ graph A2A executors


def _a2a_node(**executor) -> dict:
    return {
        "type": "task",
        "prompt": "p",
        "outputs": {"answer": {"type": "string", "description": "a"}},
        "x-magagent-executor": {"kind": "a2a", "output": "answer", **executor},
    }


def test_a2a_token_env_cannot_name_other_secrets() -> None:
    from magent.agraph.remote_executors import validate_executor

    problems = validate_executor(
        "n", _a2a_node(url="https://agents.example.com/", token_env="OPENAI_API_KEY")
    )
    assert any("A2A_" in problem for problem in problems), problems


def test_a2a_approval_names_the_token_it_sends(monkeypatch) -> None:
    from magent.agraph import remote_executors

    monkeypatch.setenv("A2A_RESEARCH_TOKEN", "value-never-shown")
    seen = []

    async def approve(action, _description):
        seen.append(action)
        return False

    node = _a2a_node(url="http://127.0.0.1:9/", token_env="A2A_RESEARCH_TOKEN")
    with pytest.raises(remote_executors.ExecutorError):
        asyncio.run(
            remote_executors.run_executor(
                "n", node, prompt="p", scope={}, mcp_servers={}, approve=approve
            )
        )
    [action] = seen
    assert action["arguments"]["bearer_token_from"] == "A2A_RESEARCH_TOKEN"
    assert "value-never-shown" not in json.dumps(action)


def test_a2a_refuses_metadata_and_private_addresses() -> None:
    from magent.agraph import remote_executors

    asked = []

    async def approve(action, _description):
        asked.append(action)
        return True

    node = _a2a_node(url="https://169.254.169.254/latest/")
    with pytest.raises(remote_executors.ExecutorError) as raised:
        asyncio.run(
            remote_executors.run_executor(
                "n", node, prompt="p", scope={}, mcp_servers={}, approve=approve
            )
        )
    assert raised.value.code == "RT049"
    assert asked == []


# --------------------------------------------------------------- --prompt-file


@pytest.mark.skipif(not Path("/dev/zero").exists(), reason="needs /dev/zero")
def test_prompt_file_must_be_a_regular_file() -> None:
    # stat() said size 0 for /dev/zero, then read_text() read forever. The
    # child gets a 1 GiB address-space cap so a regression fails fast.
    code = (
        "import resource, runpy, sys;"
        "resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30));"
        "sys.argv = ['magent', 'ask', '--prompt-file', '/dev/zero'];"
        "runpy.run_module('magent', run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "NO_COLOR": "1"},
        check=False,
    )
    assert result.returncode == 2, result.stderr[-2000:]
    assert "regular file" in result.stdout + result.stderr


# ------------------------------------------------------ parallel read tools


def test_reads_never_run_before_an_earlier_write(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from magent.cli import main as cli_main

    runner = CliRunner()
    for args in (
        ("user", "create", "sec1"),
        ("config", "set", "defaults.provider", "mock"),
        ("config", "set", "defaults.model", "offline-demo"),
        ("config", "set", "memory.auto_write", "false"),
        ("config", "set", "memory.semantic_enabled", "false"),
    ):
        result = runner.invoke(cli_main.app, list(args))
        assert result.exit_code == 0, result.output
    (tmp_path / "b.txt").write_text("bee\n", encoding="utf-8")
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            [
                {
                    "tools": [
                        {"tool": "write_file", "arguments": {"path": "a.txt", "content": "new\n"}},
                        {"tool": "read_file", "arguments": {"path": "a.txt"}},
                        {"tool": "read_file", "arguments": {"path": "b.txt"}},
                    ]
                },
                {"content": "done"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MAGENT_MOCK_SCRIPT", str(script))
    result = runner.invoke(
        cli_main.app,
        ["ask", "go", "--provider", "mock", "--project", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    calls = [
        json.loads(line)
        for path in Path.home().rglob("*.jsonl")
        if not path.name.endswith(".transcript.jsonl")
        and str(tmp_path) in path.read_text(encoding="utf-8")
        for line in path.read_text(encoding="utf-8").splitlines()
        if '"event": "tool_call"' in line
    ]
    order = [(entry["tool"], entry["args"].get("path"), entry.get("ok")) for entry in calls]
    # The write ran first and the read of the file it wrote succeeded; before
    # the fix the read ran ahead of the write and found no file.
    assert order[0] == ("write_file", "a.txt", True), order
    assert ("read_file", "a.txt", True) in order[1:], order


# -------------------------------------------------------------------- grants


def test_session_grants_do_not_leak_between_session_less_executors(tmp_path: Path) -> None:
    from magent.approval_broker import shell_action
    from magent.permissions import RiskTier
    from magent.tools.executor import ToolExecutor

    first = ToolExecutor(str(tmp_path), username="grants")
    second = ToolExecutor(str(tmp_path), username="grants")
    first._approval_broker().record_local_decision(
        shell_action("make deploy", project=tmp_path),
        origin=first._shell_grant_origin(),
        decision="approve",
        scope="session",
        actor={"id": "u", "type": "human", "authenticated_by": "test"},
    )
    assert first._shell_grant_scope("make deploy", RiskTier.CONFIRM) == "session"
    assert second._shell_grant_scope("make deploy", RiskTier.CONFIRM) is None


# ------------------------------------------------------------------ auth add


def test_config_storage_never_writes_the_key_to_a_readable_file(monkeypatch) -> None:
    from magent import auth_store
    from magent import config as magent_config

    original = magent_config.save_global_config
    modes = []

    def checking_save(cfg):
        path = Path(magent_config.GLOBAL_CONFIG)
        modes.append(path.stat().st_mode & 0o777 if path.exists() else None)
        original(cfg)

    monkeypatch.setattr(magent_config, "save_global_config", checking_save)
    old_umask = os.umask(0o022)
    try:
        if Path(magent_config.GLOBAL_CONFIG).exists():
            Path(magent_config.GLOBAL_CONFIG).unlink()
        result = auth_store.store_provider_secret("openai", "sk-test-not-real", storage="config")
    finally:
        os.umask(old_umask)
    assert result["ok"] is True
    assert modes and modes[-1] == 0o600


def test_keyring_errors_never_echo_the_key(monkeypatch) -> None:
    import types

    from magent import auth_store

    fake = types.ModuleType("keyring")

    def set_password(_service, _account, value):
        raise RuntimeError(f"backend rejected item {value}")

    fake.set_password = set_password
    monkeypatch.setitem(sys.modules, "keyring", fake)
    result = auth_store.save_keyring_secret("openai", "sk-secret-value-123")
    assert result["ok"] is False
    assert "sk-secret-value-123" not in json.dumps(result)
