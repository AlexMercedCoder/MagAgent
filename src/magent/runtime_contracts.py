"""Typed records shared across execution, provider, permission, and artifact boundaries."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class ToolResultRecord(TypedDict, total=False):
    ok: bool
    error: str
    path: str
    content: str
    output: str
    returncode: int
    permission_required: bool
    permission_denied: bool
    checkpoint_id: str
    install: str
    metadata: dict[str, Any]


class PermissionDecisionRecord(TypedDict, total=False):
    approved: bool
    tier: str
    reason: str
    scope: Literal["once", "session", "always"]
    pattern: str


class ProviderCapabilityRecord(TypedDict, total=False):
    provider: str
    model: str
    support_tier: Literal["qualified", "compatible", "experimental"]
    streaming: bool
    native_tools: bool
    cancellation: bool
    usage: bool
    caching: bool
    evidence_date: str


class ArtifactRecord(TypedDict, total=False):
    path: str
    kind: str
    status: Literal["expected", "written", "verified", "failed"]
    bytes: int
    checksum: str
    checkpoint_id: str
    error: str


class TaskRecord(TypedDict):
    id: str
    schema_version: str
    kind: str
    title: str
    state: str
    project_id: str
    project_path: str
    session_id: str
    parent_task_id: str
    created_at: str
    updated_at: str
    started_at: str
    finished_at: str
    planning_role: str
    execution_role: str
    permission_policy: str
    attempt: int
    usage: dict[str, Any]
    files_changed: list[str]
    checkpoints: list[str]
    final_audit: dict[str, Any]
    metadata: dict[str, Any]


class TaskEventRecord(TypedDict):
    event_id: str
    task_id: str
    sequence: int
    schema_version: str
    type: str
    state: str
    ts: str
    detail: dict[str, Any]
