"""Coverage for the roadmap's new features."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from magent.budgets import SpendTracker, budget_config
from magent.secrets_hygiene import secrets_hygiene_report
from magent.session_resume import list_resumable_sessions, load_session_transcript


class FakeConfig:
    def __init__(self, budgets=None):
        self._budgets = budgets or {}

    def get(self, *keys, default=None):
        if keys == ("budgets",):
            return self._budgets
        return default


class TestSpendBudgets:
    """Feature #7: token/cost telemetry was logged but never enforced."""

    def test_disabled_without_limits(self) -> None:
        tracker = SpendTracker(FakeConfig())
        assert not tracker.enabled
        assert tracker.check().ok

    def test_session_limit_stops_further_calls(self) -> None:
        tracker = SpendTracker(FakeConfig({"session_usd": 1.0}))
        tracker.record(0.4)
        assert tracker.check().ok

        tracker.record(0.7)
        verdict = tracker.check()
        assert not verdict.ok
        assert "Session budget reached" in verdict.reason

    def test_warns_once_before_the_limit(self) -> None:
        tracker = SpendTracker(FakeConfig({"session_usd": 1.0, "warn_at": 0.5}))
        tracker.record(0.6)

        first = tracker.check()
        assert first.ok and first.warning

        second = tracker.check()
        assert second.ok and not second.warning, "the warning must not repeat every round"

    def test_config_defaults_are_safe(self) -> None:
        limits = budget_config(FakeConfig({"session_usd": "not a number"}))
        assert limits["session_usd"] == 0.0
        assert 0 < limits["warn_at"] <= 1

    def test_non_numeric_costs_are_ignored(self) -> None:
        tracker = SpendTracker(FakeConfig({"session_usd": 1.0}))
        tracker.record(None)
        tracker.record("free")
        assert tracker.session_usd == 0.0


class TestSecretsHygiene:
    """Feature #10: turn audit findings into self-service doctor checks."""

    def test_flags_plaintext_keys(self, tmp_path: Path, monkeypatch) -> None:
        import magent.config as config_module

        monkeypatch.setattr(config_module, "GLOBAL_CONFIG", tmp_path / "config.toml")
        monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(
            config_module,
            "load_global_config",
            lambda: {"providers": {"openai": {"api_key": "sk-plaintext"}}},
        )

        report = secrets_hygiene_report()
        finding = next(item for item in report["findings"] if item["key"] == "plaintext_api_keys")

        assert not finding["ok"]
        assert "openai" in finding["detail"]
        assert finding["command"].startswith("magent auth add")

    def test_clean_config_passes(self, tmp_path: Path, monkeypatch) -> None:
        import magent.config as config_module

        monkeypatch.setattr(config_module, "GLOBAL_CONFIG", tmp_path / "config.toml")
        monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(
            config_module,
            "load_global_config",
            lambda: {"providers": {"openai": {"api_key_env": "OPENAI_API_KEY"}}},
        )

        assert secrets_hygiene_report()["ok"]

    def test_flags_an_open_gateway(self, tmp_path: Path, monkeypatch) -> None:
        import magent.config as config_module

        monkeypatch.setattr(config_module, "GLOBAL_CONFIG", tmp_path / "config.toml")
        monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(
            config_module,
            "load_global_config",
            lambda: {"gateway": {"allow_anyone": True, "allowed_user_ids": []}},
        )

        report = secrets_hygiene_report()
        finding = next(item for item in report["findings"] if item["key"] == "gateway_allowlist")
        assert not finding["ok"]


class TestSessionResume:
    """Feature #4: conversations were in-memory only."""

    def _write_session(self, directory: Path, session_id: str, *, transcript: bool) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        log = directory / f"{session_id}.jsonl"
        log.write_text(
            "\n".join(
                json.dumps(record)
                for record in [
                    {"ts": "2026-08-10T10:00:00+00:00", "session": session_id, "user": "alice", "event": "session_start"},
                    {"ts": "2026-08-10T10:00:01+00:00", "session": session_id, "user": "alice", "event": "user_turn", "message": "hello there"},
                    {"ts": "2026-08-10T10:00:02+00:00", "session": session_id, "user": "alice", "event": "assistant_turn", "preview": "short preview"},
                ]
            ),
            encoding="utf-8",
        )
        if transcript:
            (directory / f"{session_id}.transcript.jsonl").write_text(
                "\n".join(
                    json.dumps(record)
                    for record in [
                        {"role": "user", "content": "hello there"},
                        {"role": "assistant", "content": "a full, untruncated answer " * 20},
                    ]
                ),
                encoding="utf-8",
            )

    def test_resumes_from_the_full_transcript(self, tmp_path: Path, monkeypatch) -> None:
        import magent.config as config_module

        monkeypatch.setattr(config_module, "LOGS_DIR", tmp_path)
        self._write_session(tmp_path, "sess-1", transcript=True)

        result = load_session_transcript("sess-1")

        assert result["ok"]
        assert result["lossy"] is False
        assert len(result["conversation"][1]["content"]) > 200, "full text, not a preview"

    def test_falls_back_to_log_previews_for_older_sessions(self, tmp_path: Path, monkeypatch) -> None:
        """Sessions recorded before transcripts existed still resume, lossily."""
        import magent.config as config_module

        monkeypatch.setattr(config_module, "LOGS_DIR", tmp_path)
        self._write_session(tmp_path, "sess-old", transcript=False)

        result = load_session_transcript("sess-old")

        assert result["ok"]
        assert result["lossy"] is True
        assert result["conversation"][0]["content"] == "hello there"

    def test_lists_resumable_sessions(self, tmp_path: Path, monkeypatch) -> None:
        import magent.config as config_module

        monkeypatch.setattr(config_module, "LOGS_DIR", tmp_path)
        self._write_session(tmp_path, "sess-1", transcript=True)

        sessions = list_resumable_sessions()
        assert sessions and sessions[0]["session"] == "sess-1"
        assert sessions[0]["preview"] == "hello there"

    def test_missing_session_reports_clearly(self, tmp_path: Path, monkeypatch) -> None:
        import magent.config as config_module

        monkeypatch.setattr(config_module, "LOGS_DIR", tmp_path)
        result = load_session_transcript("nope")
        assert not result["ok"]
        assert "nope" in result["error"]


class TestGatewayAdminSurface:
    """Feature #9: operators had no way to see who can drive the gateway."""

    def test_session_report_describes_access(self) -> None:
        from magent.gateway.router import MessageRouter

        router = MessageRouter({"username": "t", "allowed_user_ids": ["U1"], "require_mention": True})
        report = router.session_report()

        assert report["ok"]
        assert report["allowed_user_ids"] == ["U1"]
        assert report["require_mention"] is True

    def test_revoke_removes_a_user(self) -> None:
        from magent.gateway.router import MessageRouter

        router = MessageRouter({"username": "t", "allowed_user_ids": ["U1", "U2"]})
        assert router.revoke_user("U1")["ok"]
        assert "U1" not in router.allowed_user_ids
        assert not router.revoke_user("U1")["ok"], "revoking twice is not a success"

    def test_revoke_closes_allow_anyone(self) -> None:
        from magent.gateway.router import MessageRouter

        router = MessageRouter({"username": "t", "allow_anyone": True})
        assert router.revoke_user("anyone")["ok"]
        assert router.allow_anyone is False


class TestProviderConformance:
    """Feature #5: bugs #24 and #26 were provider-shaped and invisible to CI."""

    def test_matrix_passes_offline(self) -> None:
        from magent.provider_conformance import conformance_matrix

        matrix = conformance_matrix()
        failures = [
            f"{case['provider']}/{case['model']}: {'; '.join(case['problems'])}"
            for check in matrix["checks"]
            for case in check["cases"]
            if not case["ok"]
        ]
        assert not failures, "provider conformance regressed:\n" + "\n".join(failures)

    def test_matrix_matches_the_recorded_fixture(self) -> None:
        """The fixture is the baseline CI compares against."""
        from magent.provider_conformance import conformance_matrix, load_fixtures

        recorded = load_fixtures()
        if not recorded:
            pytest.skip("no recorded fixture yet")

        current = conformance_matrix()
        assert [check["id"] for check in current["checks"]] == [
            check["id"] for check in recorded["checks"]
        ]
        assert current["ok"] == recorded["ok"]

    def test_temperature_workaround_is_covered(self) -> None:
        """The exact defect from bug #26: a hardcoded temperature bypassing the
        provider layer's workaround."""
        from magent.provider_conformance import conformance_matrix

        matrix = conformance_matrix()
        check = next(c for c in matrix["checks"] if c["id"] == "default-temperature-only")
        gpt5 = next(c for c in check["cases"] if c["model"].startswith("gpt-5") and c["temperature_in"] == 0.3)
        assert gpt5["observed"]["temperature"] is None


class TestMemoryHygiene:
    """Feature #8: memory grows monotonically without decay or dedup."""

    def test_finds_restatements(self) -> None:
        from magent.memory_hygiene import duplicate_groups

        nodes = [
            {"id": "a", "type": "fact", "body": "The user prefers dark mode in their editor"},
            {"id": "b", "type": "fact", "body": "the user prefers dark mode in their editor"},
            {"id": "c", "type": "fact", "body": "Deployment happens on Fridays via the release script"},
        ]
        groups = duplicate_groups(nodes)

        assert len(groups) == 1
        assert groups[0]["keep"] == "a"
        assert [m["id"] for m in groups[0]["duplicates"]] == ["b"]

    def test_does_not_merge_across_types(self) -> None:
        from magent.memory_hygiene import duplicate_groups

        nodes = [
            {"id": "a", "type": "fact", "body": "same words entirely here"},
            {"id": "b", "type": "preference", "body": "same words entirely here"},
        ]
        assert duplicate_groups(nodes) == []

    def test_decays_only_snapshot_types(self) -> None:
        from magent.memory_hygiene import stale_nodes

        nodes = [
            {"id": "old-summary", "type": "session_summary", "created_at": "2020-01-01T00:00:00+00:00"},
            {"id": "old-fact", "type": "fact", "created_at": "2020-01-01T00:00:00+00:00"},
        ]
        stale = [item["id"] for item in stale_nodes(nodes)]

        assert stale == ["old-summary"], "durable facts must not decay"

    def test_run_is_a_dry_run_by_default(self) -> None:
        from magent.memory_hygiene import run_hygiene

        deleted = []

        class FakeManager:
            available = True

            def export_json(self):
                return [
                    {"id": "a", "type": "fact", "body": "one two three four five six"},
                    {"id": "b", "type": "fact", "body": "one two three four five six"},
                ]

            def delete_node(self, node_id):
                deleted.append(node_id)
                return True

        report = run_hygiene(FakeManager())
        assert report["targets"] == ["b"]
        assert report["applied"] is False
        assert deleted == [], "memory is the user's; nothing is removed unless asked"

        applied = run_hygiene(FakeManager(), apply=True)
        assert applied["applied"] is True
        assert deleted == ["b"]


class TestShellSandbox:
    """Feature #3: isolation for run_shell, independent of the permission tier."""

    def test_off_does_not_wrap(self, tmp_path) -> None:
        from magent.sandbox import wrap_shell_command

        assert wrap_shell_command("ls", profile="off", cwd=tmp_path) is None

    def test_unknown_profile_is_rejected(self, tmp_path) -> None:
        from magent.sandbox import wrap_shell_command

        with pytest.raises(ValueError):
            wrap_shell_command("ls", profile="nonsense", cwd=tmp_path)

    def test_docker_profile_drops_network_and_privileges(self, tmp_path, monkeypatch) -> None:
        import magent.sandbox as sandbox_module
        from magent.sandbox import wrap_shell_command

        monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: "/usr/bin/docker")
        argv = wrap_shell_command("ls", profile="docker", cwd=tmp_path)

        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
        assert "--cap-drop" in argv
        assert "no-new-privileges" in argv

    def test_network_can_be_opted_into(self, tmp_path, monkeypatch) -> None:
        import magent.sandbox as sandbox_module
        from magent.sandbox import wrap_shell_command

        monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: "/usr/bin/docker")
        argv = wrap_shell_command("ls", profile="docker", cwd=tmp_path, network=True)

        assert "--network" not in argv
