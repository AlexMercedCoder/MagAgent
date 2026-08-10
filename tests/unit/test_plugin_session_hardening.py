"""Regressions for plugin path handling and session-messaging runtime safety."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from magent import plugins, session_messaging


class TestPluginPathContainment:
    def test_report_entries_cannot_escape_the_package(self, tmp_path: Path) -> None:
        """`preserved.extensions` comes from inside the plugin and became
        `--extension` subprocess arguments."""
        with pytest.raises(ValueError):
            plugins._contained_paths(tmp_path, ["../../../etc/passwd"], "extensions")

        with pytest.raises(ValueError):
            plugins._contained_paths(tmp_path, ["/etc/passwd"], "extensions")

    def test_ordinary_entries_resolve(self, tmp_path: Path) -> None:
        resolved = plugins._contained_paths(tmp_path, ["ext/a.js", "b.js"], "extensions")
        assert [path.name for path in resolved] == ["a.js", "b.js"]
        assert all(str(path).startswith(str(tmp_path.resolve())) for path in resolved)

    def test_non_string_entries_are_ignored(self, tmp_path: Path) -> None:
        assert plugins._contained_paths(tmp_path, [None, 3, "", "ok.js"], "extensions")[0].name == "ok.js"

    def test_bridge_survives_a_malformed_report(self, tmp_path: Path, monkeypatch) -> None:
        """Direct `report["preserved"]["extensions"]` indexing raised an
        uncaught KeyError on a malformed report."""
        monkeypatch.setattr(plugins, "PLUGIN_DIR", tmp_path / "plugins")
        package = tmp_path / "plugins" / "demo" / "compatibility" / "pi"
        package.mkdir(parents=True)
        (package / "report.json").write_text(json.dumps({}), encoding="utf-8")
        monkeypatch.setattr(
            plugins,
            "_state",
            lambda: {"demo": {"enabled": True, "grants": {"user": ["external_process"]}}},
        )

        result = plugins.run_pi_plugin_bridge("demo", project=str(tmp_path), dry_run=True)
        assert result["ok"] is True
        assert "--extension" not in result["command"]

    def test_bridge_refuses_escaping_extension_paths(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(plugins, "PLUGIN_DIR", tmp_path / "plugins")
        package = tmp_path / "plugins" / "demo" / "compatibility" / "pi"
        package.mkdir(parents=True)
        (package / "report.json").write_text(
            json.dumps({"preserved": {"extensions": ["../../../../etc/passwd"]}}), encoding="utf-8"
        )
        monkeypatch.setattr(
            plugins,
            "_state",
            lambda: {"demo": {"enabled": True, "grants": {"user": ["external_process"]}}},
        )

        result = plugins.run_pi_plugin_bridge("demo", project=str(tmp_path), dry_run=True)
        assert result["ok"] is False
        assert "escapes" in result["error"]


class TestPluginMcpValidation:
    def test_rejects_bad_shapes(self) -> None:
        assert plugins._mcp_server_problem("ok", {"command": "srv"}) == ""
        assert plugins._mcp_server_problem("../evil", {"command": "srv"})
        assert plugins._mcp_server_problem("ok", "not-a-table")
        assert plugins._mcp_server_problem("ok", {})
        assert plugins._mcp_server_problem("ok", {"command": "srv", "args": "not-a-list"})
        assert plugins._mcp_server_problem("ok", {"command": "srv", "env": {"K": 1}})


class TestSessionMessagingRuntime:
    def test_runtime_dir_prefers_xdg_runtime_dir(self, tmp_path: Path, monkeypatch) -> None:
        """/tmp is world-writable: another user can pre-create the predictable
        directory and own the parent of our sockets."""
        runtime = tmp_path / "run"
        runtime.mkdir()
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
        assert session_messaging._runtime_root() == runtime

    def test_runtime_dir_falls_back_when_xdg_is_unusable(self, monkeypatch) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/nonexistent-magent-runtime")
        assert session_messaging._runtime_root() != Path("/nonexistent-magent-runtime")

    @pytest.mark.skipif(os.name != "posix", reason="POSIX ownership check")
    def test_world_accessible_runtime_dir_is_refused(self, tmp_path: Path) -> None:
        loose = tmp_path / "loose"
        loose.mkdir(mode=0o777)
        os.chmod(loose, 0o777)
        with pytest.raises(PermissionError):
            session_messaging._assert_private_dir(loose)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX ownership check")
    def test_private_runtime_dir_is_accepted(self, tmp_path: Path) -> None:
        tight = tmp_path / "tight"
        tight.mkdir(mode=0o700)
        os.chmod(tight, 0o700)
        session_messaging._assert_private_dir(tight)

    def test_peer_records_are_written_private(self, tmp_path: Path) -> None:
        record = tmp_path / "peer.json"
        session_messaging._atomic_json(record, {"capability": "secret"})
        assert record.stat().st_mode & 0o077 == 0

    def test_ephemeral_peer_does_not_crash_delivery(self) -> None:
        """`endpoint: "ephemeral"` used to reach rsplit(':') and raise an
        unhandled ValueError, leaking the socket it had already created."""
        result = session_messaging._send_wire(
            {"transport": "ephemeral", "endpoint": "ephemeral"}, {"hello": "world"}, 0.5
        )
        assert result["status"] == "unreachable"

    def test_malformed_tcp_endpoint_is_reported(self) -> None:
        result = session_messaging._send_wire(
            {"transport": "tcp", "endpoint": "no-port-here"}, {"hello": "world"}, 0.5
        )
        assert result["status"] == "unreachable"

    def test_live_pid_survives_an_expired_ttl(self) -> None:
        """A session running longer than the TTL used to be unregistered and
        have its live socket deleted, with nothing to re-register it."""
        peer = {
            "endpoint": "/tmp/whatever.sock",
            "pid": os.getpid(),
            "registered_at": "2000-01-01T00:00:00+00:00",
            "heartbeat_at": session_messaging._now(),
        }
        assert session_messaging._peer_is_live(peer) is True

    def test_dead_pid_is_not_live(self) -> None:
        peer = {
            "endpoint": "/tmp/whatever.sock",
            "pid": 999_999_999,
            "heartbeat_at": session_messaging._now(),
        }
        assert session_messaging._peer_is_live(peer) is False
