from __future__ import annotations

from magent.runtime_contracts import (
    ArtifactRecord,
    PermissionDecisionRecord,
    ProviderCapabilityRecord,
    TaskEventRecord,
    TaskRecord,
    ToolResultRecord,
)


def test_boundary_records_keep_optional_payloads_additive() -> None:
    for record in (
        ToolResultRecord,
        PermissionDecisionRecord,
        ProviderCapabilityRecord,
        ArtifactRecord,
    ):
        assert record.__required_keys__ == frozenset()
        assert record.__optional_keys__

    assert {"ok", "error", "metadata"} <= ToolResultRecord.__optional_keys__
    assert {"approved", "scope", "pattern"} <= PermissionDecisionRecord.__optional_keys__
    assert {"provider", "model", "support_tier"} <= ProviderCapabilityRecord.__optional_keys__
    assert {"path", "kind", "status", "checksum"} <= ArtifactRecord.__optional_keys__


def test_durable_task_contracts_require_identity_state_and_ordering() -> None:
    assert {
        "id",
        "schema_version",
        "state",
        "project_id",
        "session_id",
        "created_at",
        "updated_at",
        "metadata",
    } <= TaskRecord.__required_keys__
    assert TaskRecord.__optional_keys__ == frozenset()

    assert {
        "event_id",
        "task_id",
        "sequence",
        "schema_version",
        "type",
        "state",
        "ts",
        "detail",
    } == TaskEventRecord.__required_keys__
    assert TaskEventRecord.__optional_keys__ == frozenset()
