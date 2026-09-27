"""AAIS authority broker shared by every MagAgent execution surface.

The broker is deliberately independent from HTTP, the terminal, and the graph
runtime.  A presenter receives validated AAIS envelopes and sends a decision
back here; this class remains the authority that persists, revalidates, and
atomically resolves the exact action before the waiting tool may continue.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from aais import (
    ApprovalStore,
    ConflictError,
    action_digest,
    create_decision,
    create_request,
    validate,
)

from magent.workbench_store import WorkbenchStore, WorkbenchStoreError

Envelope = dict[str, Any]
Publisher = Callable[[Envelope], None]
CurrentAction = Callable[[], Mapping[str, Any]]

# D6: persistent grants expire after this many days unless configured
# otherwise with ``permissions.grant_ttl_days`` (0 disables expiry).
DEFAULT_GRANT_TTL_DAYS = 30
EVENT_LOG_LIMIT = 1000
GRANT_HIT_LIMIT = 1000
_GRANT_ACTOR = {"type": "policy", "authenticated_by": "authority"}


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def configured_grant_ttl_days(username: str | None = None) -> int:
    """Return the configured persistent-grant lifetime in days (0 = never expires)."""

    try:
        from magent.config import load_config

        return max(0, int(load_config(username).approval_grant_ttl_days))
    except Exception:
        return DEFAULT_GRANT_TTL_DAYS


def grant_id_for(grant: Mapping[str, Any]) -> str:
    """Stable identifier for a grant, including grants stored before ids existed."""

    if grant.get("id"):
        return str(grant["id"])
    seed = "|".join(
        str(grant.get(key) or "") for key in ("action_digest", "scope", "session_id", "created_at")
    )
    return "grt_legacy_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def grant_status(grant: Mapping[str, Any], now: datetime | None = None) -> str:
    """Return ``active``, ``expired`` or ``revoked`` for one stored grant."""

    if grant.get("revoked_at"):
        return "revoked"
    expires = _parse_timestamp(grant.get("expires_at"))
    if expires is not None and (now or _now()) >= expires:
        return "expired"
    return "active"


def legacy_action(description: str, *, project: str | Path = ".") -> Envelope:
    """Project the older description/tier callback into an exact AAIS action."""

    text = str(description).strip() or "Protected action"
    command = text[4:].strip() if text.casefold().startswith("run:") else ""
    if command:
        return {
            "kind": "tool.call",
            "name": "shell.exec",
            "summary": text,
            "arguments": {"command": command},
            "working_directory": str(Path(project).resolve()),
            "effects": ["Executes a local process in the selected project."],
        }
    return {
        "kind": "tool.call",
        "name": "magent.protected_action",
        "summary": text,
        "arguments": {"description": text},
        "working_directory": str(Path(project).resolve()),
        "effects": ["Performs an action guarded by the active MagAgent permission policy."],
    }


@dataclass
class _Waiter:
    envelope: Envelope
    current_action: CurrentAction
    resolved: threading.Event
    resolution: Envelope | None = None


class ApprovalBroker:
    """Durable, replay-safe AAIS authority for one MagAgent process."""

    STORE_NAME = "aais_approvals"

    def __init__(
        self,
        store: WorkbenchStore,
        *,
        project: str | Path,
        stream: str = "magent.approvals",
        grant_ttl_days: int | None = None,
    ) -> None:
        self.store = store
        self.project = str(Path(project).resolve())
        self.stream = stream
        self.grant_ttl_days = (
            configured_grant_ttl_days(getattr(store, "username", None))
            if grant_ttl_days is None
            else max(0, int(grant_ttl_days))
        )
        self._lock = threading.RLock()
        self._waiters: dict[str, _Waiter] = {}
        self._publishers: dict[str, Publisher] = {}

    @staticmethod
    def _empty() -> Envelope:
        return {
            "schema": "magent.aais-store.v1",
            "sequence": 0,
            "presenter_sequence": 0,
            "pending": {},
            "resolutions": {},
            "decisions": {},
            "grants": [],
            "events": [],
        }

    def _state(self) -> Envelope:
        state = self.store.read(self.STORE_NAME, self._empty(), strict=True)
        if (
            not isinstance(state, dict)
            or state.get("schema") != self._empty()["schema"]
            or any(
                key not in state or not isinstance(state[key], type(default))
                for key, default in self._empty().items()
            )
        ):
            raise WorkbenchStoreError("Invalid approval state; explicit recovery is required")
        return state

    def _next_sequence(self, state: Envelope, key: str = "sequence") -> int:
        value = int(state.get(key, 0)) + 1
        state[key] = value
        return value

    def request_legacy(
        self,
        description: str,
        tier: int,
        *,
        origin: Mapping[str, Any],
        publish: Publisher,
        timeout: float,
        allow_session: bool = True,
        allow_persistent: bool = False,
    ) -> str:
        action = legacy_action(description, project=self.project)
        return self.request(
            action,
            origin=origin,
            risk_level={0: "low", 1: "low", 2: "medium", 3: "high"}.get(int(tier), "high"),
            risk_reasons=[f"MagAgent permission tier {int(tier)} requires an explicit decision."],
            publish=publish,
            timeout=timeout,
            allow_session=allow_session,
            allow_persistent=allow_persistent,
        )

    def request_prompt(
        self,
        description: str,
        tier: int,
        action: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Resolve a permission callback using exact action data when available."""

        if action is None:
            return self.request_legacy(description, tier, **kwargs)
        return self.request(
            action,
            risk_level={0: "low", 1: "low", 2: "medium", 3: "high"}.get(int(tier), "high"),
            risk_reasons=[f"MagAgent permission tier {int(tier)} requires approval."],
            **kwargs,
        )

    def request(
        self,
        action: Mapping[str, Any],
        *,
        origin: Mapping[str, Any],
        risk_level: str,
        risk_reasons: list[str],
        publish: Publisher,
        timeout: float,
        allow_session: bool = True,
        allow_persistent: bool = False,
        current_action: CurrentAction | None = None,
    ) -> str:
        exact_action = copy.deepcopy(dict(action))
        digest = action_digest(exact_action)
        with self._lock, self.store.lock(self.STORE_NAME):
            state = self._state()
            session_id = str(origin.get("session_id") or "")
            now = _now()
            remembered = next(
                (
                    item
                    for item in state.get("grants", [])
                    if item.get("action_digest") == digest
                    and item.get("scope") in {"session", "persistent"}
                    and grant_status(item, now) == "active"
                    and (item.get("scope") == "persistent" or item.get("session_id") == session_id)
                ),
                None,
            )
            if remembered is not None:
                self._record_grant_hit(
                    state,
                    remembered,
                    exact_action,
                    origin=origin,
                    risk_level=risk_level,
                    risk_reasons=risk_reasons,
                    now=now,
                )
                self.store.write(self.STORE_NAME, state)
                return str(remembered["scope"])
            choices: list[Envelope] = [
                {"decision": "approve", "scope": "once", "label": "Allow once"}
            ]
            if allow_session:
                choices.append(
                    {
                        "decision": "approve",
                        "scope": "session",
                        "label": "Allow this exact action for this session",
                        "scope_constraints": {"action_digest": digest},
                    }
                )
            if allow_persistent:
                choices.append(
                    {
                        "decision": "approve",
                        "scope": "persistent",
                        "label": "Always allow this exact action",
                        "scope_constraints": {"action_digest": digest},
                    }
                )
            choices.append({"decision": "deny", "scope": "once", "label": "Deny"})
            created = _now()
            envelope = create_request(
                action=exact_action,
                origin={
                    "harness": "magagent",
                    "project": self.project,
                    **dict(origin),
                },
                risk={"level": risk_level, "reasons": risk_reasons or ["Protected action."]},
                choices=choices,
                sequence=self._next_sequence(state),
                stream=self.stream,
                created_at=_timestamp(created),
                expires_at=_timestamp(created + timedelta(seconds=max(1.0, timeout))),
            )
            request_id = str(envelope["request"]["id"])
            state.setdefault("pending", {})[request_id] = envelope
            state.setdefault("owners", {})[request_id] = os.getpid()
            self._append_events(state, envelope)
            self.store.write(self.STORE_NAME, state)
            waiter = _Waiter(
                envelope=envelope,
                current_action=current_action or (lambda: exact_action),
                resolved=threading.Event(),
            )
            self._waiters[request_id] = waiter
            self._publishers[request_id] = publish
        publish(copy.deepcopy(envelope))
        deadline = time.monotonic() + timeout
        while not waiter.resolved.wait(min(0.1, max(0, deadline - time.monotonic()))):
            with self._lock, self.store.lock(self.STORE_NAME):
                durable = self._state().get("resolutions", {}).get(request_id)
            if durable:
                waiter.resolution = durable
                publish(copy.deepcopy(durable))
                break
            if time.monotonic() >= deadline:
                with suppress(ConflictError, ValueError):
                    self.decide(
                        request_id,
                        decision="deny",
                        scope="once",
                        actor={
                            "id": "magent.timeout",
                            "type": "policy",
                            "authenticated_by": "authority",
                        },
                    )
                with self._lock, self.store.lock(self.STORE_NAME):
                    waiter.resolution = self._state().get("resolutions", {}).get(request_id)
                break
        with self._lock:
            resolution = waiter.resolution
            self._waiters.pop(request_id, None)
            self._publishers.pop(request_id, None)
        if not resolution:
            return "deny"
        body = resolution["resolution"]
        if body["outcome"] == "approved" and action_digest(waiter.current_action()) != digest:
            return "deny"
        return str(body.get("effective_scope", "deny")) if body["outcome"] == "approved" else "deny"

    def decide(
        self,
        request_id: str,
        *,
        decision: str,
        scope: str,
        actor: Mapping[str, Any],
        decision_id: str | None = None,
        reviewed_digest: str | None = None,
    ) -> Envelope:
        publisher: Publisher | None = None
        waiter: _Waiter | None = None
        with self._lock, self.store.lock(self.STORE_NAME):
            state = self._state()
            prior = state.get("resolutions", {}).get(request_id)
            prior_decision = state.get("decisions", {}).get(request_id)
            pending = state.get("pending", {}).get(request_id)
            if prior is not None:
                if prior_decision and (
                    prior_decision["decision"]["decision"],
                    prior_decision["decision"]["scope"],
                ) == (decision, scope):
                    return copy.deepcopy(prior)
                raise ConflictError(f"request {request_id} was already resolved")
            if pending is None:
                raise ValueError(f"unknown pending approval: {request_id}")
            if (
                reviewed_digest is not None
                and reviewed_digest != pending["request"]["action_digest"]
            ):
                raise ConflictError("Decision digest does not match the reviewed action")
            owner = state.get("owners", {}).get(request_id)
            if decision == "approve" and owner is not None and not self._owner_alive(owner):
                raise ConflictError(
                    "The issuing process stopped; inspect recovery before starting new work"
                )
            decided = create_decision(
                pending,
                decision=decision,
                scope=scope,
                actor=dict(actor),
                sequence=self._next_sequence(state, "presenter_sequence"),
                stream="magent.presenter",
                decision_id=decision_id,
            )
            waiter = self._waiters.get(request_id)
            current = waiter.current_action() if waiter else pending["request"]["action"]
            machine = ApprovalStore()
            machine.add(pending)
            resolution = machine.decide(
                decided,
                current_action=current,
                sequence=self._next_sequence(state),
            )
            state.setdefault("pending", {}).pop(request_id, None)
            state.setdefault("decisions", {})[request_id] = decided
            state.setdefault("resolutions", {})[request_id] = resolution
            self._append_events(state, resolution)
            if resolution["resolution"]["outcome"] == "approved" and scope in {
                "session",
                "persistent",
            }:
                state.setdefault("grants", []).append(
                    self._new_grant(pending, scope, resolution, actor=actor)
                )
            self.store.write(self.STORE_NAME, state)
            publisher = self._publishers.get(request_id)
            if waiter:
                waiter.resolution = resolution
        if publisher:
            publisher(copy.deepcopy(resolution))
        if waiter:
            waiter.resolved.set()
        return copy.deepcopy(resolution)

    # ------------------------------------------------------------------ grants

    @staticmethod
    def _append_events(state: Envelope, *envelopes: Envelope) -> None:
        events = state.setdefault("events", [])
        events.extend(envelopes)
        state["events"] = events[-EVENT_LOG_LIMIT:]

    def _new_grant(
        self,
        pending: Envelope,
        scope: str,
        resolution: Envelope,
        *,
        actor: Mapping[str, Any],
    ) -> Envelope:
        request = pending["request"]
        action = request.get("action", {})
        created_at = str(resolution["occurred_at"])
        grant: Envelope = {
            "id": f"grt_{uuid4().hex[:20]}",
            "action_digest": request["action_digest"],
            "scope": scope,
            "session_id": str(request.get("origin", {}).get("session_id") or ""),
            "created_at": created_at,
            "request_id": str(request["id"]),
            "action_name": str(action.get("name") or ""),
            "action_summary": str(action.get("summary") or ""),
            "granted_by": str(actor.get("id") or ""),
            "hits": 0,
        }
        if scope == "persistent" and self.grant_ttl_days > 0:
            created = _parse_timestamp(created_at) or _now()
            grant["expires_at"] = _timestamp(created + timedelta(days=self.grant_ttl_days))
        return grant

    def _record_grant_hit(
        self,
        state: Envelope,
        grant: Envelope,
        action: Envelope,
        *,
        origin: Mapping[str, Any],
        risk_level: str,
        risk_reasons: list[str],
        now: datetime,
    ) -> Envelope:
        """Write an AAIS receipt for an action a remembered grant approved.

        A grant hit used to return silently, so the audit trail showed nothing
        for every repeat of a remembered action. The hit is now recorded as a
        complete requested/decided/resolved exchange whose decision actor is
        the grant itself, plus a compact entry in ``grant_hits``.
        """

        grant_id = grant_id_for(grant)
        scope = str(grant["scope"])
        digest = str(grant["action_digest"])
        stamp = _timestamp(now)
        requested = create_request(
            action=action,
            origin={
                "harness": "magagent",
                "project": self.project,
                **dict(origin),
            },
            risk={"level": risk_level, "reasons": risk_reasons or ["Protected action."]},
            choices=[
                {
                    "decision": "approve",
                    "scope": scope,
                    "label": "Approved by a remembered grant",
                    "scope_constraints": {"action_digest": digest},
                },
                {"decision": "deny", "scope": "once", "label": "Deny"},
            ],
            sequence=self._next_sequence(state),
            stream=self.stream,
            created_at=stamp,
        )
        decided = create_decision(
            requested,
            decision="approve",
            scope=scope,
            actor={"id": f"magent.grant:{grant_id}", **_GRANT_ACTOR},
            sequence=self._next_sequence(state, "presenter_sequence"),
            stream="magent.grants",
            decided_at=stamp,
        )
        machine = ApprovalStore()
        machine.add(requested)
        resolution = machine.decide(
            decided, now=now, current_action=action, sequence=self._next_sequence(state)
        )
        request_id = str(requested["request"]["id"])
        state.setdefault("decisions", {})[request_id] = decided
        state.setdefault("resolutions", {})[request_id] = resolution
        self._append_events(state, requested, resolution)
        grant["id"] = grant_id
        grant["hits"] = int(grant.get("hits", 0) or 0) + 1
        grant["last_used_at"] = stamp
        receipt = {
            "grant_id": grant_id,
            "request_id": request_id,
            "resolution_id": resolution["resolution"]["id"],
            "action_digest": digest,
            "scope": scope,
            "session_id": str(origin.get("session_id") or ""),
            "occurred_at": stamp,
        }
        hits = state.setdefault("grant_hits", [])
        hits.append(receipt)
        state["grant_hits"] = hits[-GRANT_HIT_LIMIT:]
        return receipt

    def _action_details(self, state: Envelope, digest: str) -> Envelope:
        for event in reversed(state.get("events", [])):
            request = event.get("request") if isinstance(event, dict) else None
            if isinstance(request, dict) and request.get("action_digest") == digest:
                action = request.get("action", {})
                return {
                    "action_name": str(action.get("name") or ""),
                    "action_summary": str(action.get("summary") or ""),
                }
        return {}

    def list_grants(self, *, include_inactive: bool = True) -> list[Envelope]:
        """Return remembered grants with status, expiry and legacy flags."""

        with self._lock, self.store.lock(self.STORE_NAME):
            state = self._state()
        now = _now()
        rows: list[Envelope] = []
        for grant in state.get("grants", []):
            if not isinstance(grant, dict):
                continue
            status = grant_status(grant, now)
            if not include_inactive and status != "active":
                continue
            legacy = not grant.get("id")
            details = {
                "action_name": grant.get("action_name", ""),
                "action_summary": grant.get("action_summary", ""),
            }
            if legacy or not details["action_summary"]:
                details = {
                    **details,
                    **self._action_details(state, str(grant.get("action_digest"))),
                }
            row: Envelope = {
                "id": grant_id_for(grant),
                "scope": grant.get("scope", ""),
                "status": status,
                "action_digest": grant.get("action_digest", ""),
                "action_name": details.get("action_name", ""),
                "action_summary": details.get("action_summary", ""),
                "session_id": grant.get("session_id", ""),
                "created_at": grant.get("created_at", ""),
                "expires_at": grant.get("expires_at"),
                "last_used_at": grant.get("last_used_at"),
                "hits": int(grant.get("hits", 0) or 0),
                "legacy": legacy,
            }
            if grant.get("revoked_at"):
                row["revoked_at"] = grant["revoked_at"]
                row["revoked_by"] = grant.get("revoked_by", "")
            if legacy and grant.get("scope") == "persistent" and not grant.get("expires_at"):
                row["flag"] = (
                    "Created before grant expiry existed; it never expires. "
                    "Revoke it and approve again to get an expiring grant."
                )
            rows.append(row)
        return rows

    def revoke_grants(
        self,
        grant_ids: list[str] | None = None,
        *,
        expired: bool = False,
        all_grants: bool = False,
        actor: str = "local-user",
    ) -> Envelope:
        """Revoke grants by id, every expired grant, or every active grant."""

        wanted = {str(item) for item in grant_ids or []}
        stamp = _timestamp(_now())
        revoked: list[str] = []
        with self._lock, self.store.lock(self.STORE_NAME):
            state = self._state()
            now = _now()
            known = {
                grant_id_for(item) for item in state.get("grants", []) if isinstance(item, dict)
            }
            missing = sorted(wanted - known)
            for grant in state.get("grants", []):
                if not isinstance(grant, dict):
                    continue
                status = grant_status(grant, now)
                identifier = grant_id_for(grant)
                if status == "revoked":
                    continue
                if (
                    identifier in wanted
                    or (expired and status == "expired")
                    or (all_grants and status == "active")
                ):
                    grant["id"] = identifier
                    grant["revoked_at"] = stamp
                    grant["revoked_by"] = actor
                    revoked.append(identifier)
            if revoked:
                self.store.write(self.STORE_NAME, state)
        return {"ok": not missing, "revoked": revoked, "missing": missing}

    def grant_hits(self, limit: int = 100) -> list[Envelope]:
        with self._lock, self.store.lock(self.STORE_NAME):
            hits = list(self._state().get("grant_hits", []))
        return [copy.deepcopy(item) for item in hits[-max(1, limit) :]]

    def cancel_owner(self, **origin: str) -> int:
        snapshot = self.snapshot()
        matches = [
            request
            for request in snapshot["snapshot"]["pending"]
            if all(
                str(request.get("origin", {}).get(key, "")) == value
                for key, value in origin.items()
            )
        ]
        for request in matches:
            with suppress(ConflictError, ValueError):
                self.decide(
                    str(request["id"]),
                    decision="cancel",
                    scope="once",
                    actor={
                        "id": "magent.cancel",
                        "type": "policy",
                        "authenticated_by": "authority",
                    },
                )
        return len(matches)

    def cancel_active(self) -> int:
        """Cancel only requests owned by this live broker instance."""

        with self._lock:
            request_ids = list(self._waiters)
        for request_id in request_ids:
            with suppress(ConflictError, ValueError):
                self.decide(
                    request_id,
                    decision="cancel",
                    scope="once",
                    actor={
                        "id": "magent.cancel",
                        "type": "policy",
                        "authenticated_by": "authority",
                    },
                )
        return len(request_ids)

    @staticmethod
    def _owner_alive(pid: int | None) -> bool:
        from magent.process_liveness import process_alive

        return process_alive(pid)

    def recovery(self) -> Envelope:
        with self._lock, self.store.lock(self.STORE_NAME):
            state = self._state()
            owners = state.get("owners", {})
            return {
                "orphaned": [
                    key
                    for key in state["pending"]
                    if key in owners and not self._owner_alive(owners[key])
                ],
                "unknown_owner": [key for key in state["pending"] if key not in owners],
                "receipts": list(state["resolutions"].values())[-100:],
                "guidance": "Stopped owners are not restarted. Inspect completed effects before creating a new run.",
            }

    def snapshot(self) -> Envelope:
        with self._lock:
            state = self._state()
            machine = ApprovalStore(last_sequence=int(state.get("sequence", 0)))
            for key, envelope in state.get("pending", {}).items():
                owner = state.get("owners", {}).get(key)
                if owner is None or self._owner_alive(owner):
                    machine.add(validate(envelope))
            return machine.snapshot(stream=self.stream)

    def events_after(self, sequence: int) -> list[Envelope]:
        with self._lock:
            return [
                copy.deepcopy(item)
                for item in self._state().get("events", [])
                if int(item.get("sequence", 0)) > sequence
            ]


def start_stdio_broker(
    store: WorkbenchStore,
    *,
    project: str | Path,
    stream: str,
) -> tuple[ApprovalBroker, Publisher]:
    """Start the AAIS NDJSON decision reader used by headless desktop clients."""

    broker = ApprovalBroker(store, project=project, stream=stream)

    def publish(envelope: Envelope) -> None:
        print(json.dumps(envelope, separators=(",", ":"), default=str), flush=True)

    def read_decisions() -> None:
        try:
            for line in sys.stdin:
                try:
                    envelope = validate(json.loads(line))
                    if envelope.get("type") != "approval.decided":
                        continue
                    decision = envelope["decision"]
                    broker.decide(
                        str(decision["request_id"]),
                        decision=str(decision["decision"]),
                        scope=str(decision["scope"]),
                        actor={
                            "id": "stdio-user",
                            "type": "human",
                            "authenticated_by": "aais-ndjson-stdio",
                        },
                        decision_id=str(decision.get("id") or "") or None,
                        reviewed_digest=str(decision["action_digest"]),
                    )
                except Exception as error:  # malformed input never grants authority
                    print(
                        json.dumps({"type": "aais.error", "error": str(error)}),
                        file=sys.stderr,
                        flush=True,
                    )
        finally:
            broker.cancel_active()

    def terminate(_signum: int, _frame: Any) -> None:
        broker.cancel_active()
        raise SystemExit(143)

    threading.Thread(target=read_decisions, daemon=True, name="magent-aais-stdin").start()
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, terminate)
    return broker, publish
