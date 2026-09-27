"""AAIS authority broker shared by every MagAgent execution surface.

The broker is deliberately independent from HTTP, the terminal, and the graph
runtime. A presenter receives validated AAIS envelopes and sends a decision
back here; this class remains the authority that persists, revalidates, and
atomically resolves the exact action before the waiting tool may continue.

Since 1.4 the durable state lives in the shared ``aais.store.FileApprovalStore``
from ``agent-approval-interchange`` 0.2 (whole-transaction cross-process
locking, PID-reuse-safe owner identity, bounded retention with explicit replay
gaps, corruption quarantine). MagAgent keeps only its own policy on top:
remembered grants, stored as a store extension and checked in the same
transaction that would otherwise create a new request.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from aais import ConflictError, action_digest, validate
from aais.store import (
    FileApprovalStore,
    RecoveryRequired,
    RetentionPolicy,
    StoreError,
    StoreTransaction,
    UnknownRequestError,
)

from magent.approval_bus import (
    DOORBELLS,
    MAX_DOORBELLS,
    SAFETY_POLL_SECONDS,
    Doorbell,
    DoorbellWatcher,
    ring_all,
)
from magent.workbench_store import WorkbenchStore, WorkbenchStoreError

Envelope = dict[str, Any]
Publisher = Callable[[Envelope], None]
CurrentAction = Callable[[], Mapping[str, Any]]

# D6: persistent grants expire after this many days unless configured
# otherwise with ``permissions.grant_ttl_days`` (0 disables expiry).
DEFAULT_GRANT_TTL_DAYS = 30
GRANT_HIT_LIMIT = 1000
LOCK_TIMEOUT_SECONDS = 30.0
STATE_FILE = "aais-approvals.json"
LEGACY_STATE_FILE = "aais_approvals.json"
GRANTS = "grants"
GRANT_HITS = "grant_hits"
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


def shell_action(command: str, *, project: str | Path = ".") -> Envelope:
    """The exact AAIS action for running ``command`` in ``project``."""

    return {
        "kind": "tool.call",
        "name": "shell.exec",
        "summary": f"Run: {command}",
        "arguments": {"command": command},
        "working_directory": str(Path(project).resolve()),
        "effects": ["Executes a local process in the selected project."],
    }


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


def _risk_level(tier: int) -> str:
    return {0: "low", 1: "low", 2: "medium", 3: "high"}.get(int(tier), "high")


@dataclass
class _Waiter:
    envelope: Envelope
    current_action: CurrentAction
    resolved: threading.Event
    resolution: Envelope | None = None


class ApprovalBroker:
    """Durable, replay-safe AAIS authority for one MagAgent process."""

    STATE_FILE = STATE_FILE

    def __init__(
        self,
        store: WorkbenchStore,
        *,
        project: str | Path,
        stream: str = "magent.approvals",
        grant_ttl_days: int | None = None,
        retention: RetentionPolicy | None = None,
    ) -> None:
        self.store = store
        self.project = str(Path(project).resolve())
        self.stream = stream
        self.grant_ttl_days = (
            configured_grant_ttl_days(getattr(store, "username", None))
            if grant_ttl_days is None
            else max(0, int(grant_ttl_days))
        )
        root = Path(store.root)
        self.path = root / STATE_FILE
        self.legacy_path = root / LEGACY_STATE_FILE
        self.file = FileApprovalStore(
            self.path,
            stream=stream,
            presenter_stream="magent.presenter",
            retention=retention,
            # Each write fsyncs the file and its directory. On a slow or busy
            # disk a queue of writers can exceed the library's 10s default.
            lock_timeout=LOCK_TIMEOUT_SECONDS,
        )
        self._lock = threading.RLock()
        self._waiters: dict[str, _Waiter] = {}
        self._publishers: dict[str, Publisher] = {}
        self._listeners: list[Callable[[Envelope], None]] = []
        self._migrated = False
        self._doorbell: Doorbell | None = None
        self._watchers: list[DoorbellWatcher] = []

    # ------------------------------------------------------------- plumbing

    def _migrate(self) -> None:
        """Import the pre-1.4 ``aais_approvals.json`` once, then set it aside."""

        if self._migrated:
            return
        if self.legacy_path.exists() and not self.path.exists():
            try:
                legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
                if not isinstance(legacy, dict) or legacy.get("schema") != "magent.aais-store.v1":
                    raise ValueError("unrecognized legacy approval state")
            except (OSError, ValueError) as error:
                raise WorkbenchStoreError(
                    f"Invalid approval state in {self.legacy_path}: {error}. "
                    "Explicit recovery is required; the file was left untouched."
                ) from error
            with suppress(StoreError):  # another process imported it first
                self.file.import_legacy_state(legacy)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            with suppress(OSError):
                self.legacy_path.replace(
                    self.legacy_path.with_name(f"{LEGACY_STATE_FILE}.migrated-{stamp}")
                )
        self._migrated = True

    @contextlib.contextmanager
    def transaction(self) -> Iterator[StoreTransaction]:
        """A locked store transaction, with store errors reported MagAgent's way."""

        self._migrate()
        try:
            with self.file.transaction() as tx:
                yield tx
        except RecoveryRequired as error:
            raise WorkbenchStoreError(
                f"Approval state needs recovery: {error.reason}. It was quarantined to "
                f"{error.quarantined_to}; explicit recovery is required."
            ) from error

    def _read(self, call: Callable[[], Any]) -> Any:
        self._migrate()
        try:
            return call()
        except RecoveryRequired as error:
            raise WorkbenchStoreError(
                f"Approval state needs recovery: {error.reason}; explicit recovery is required."
            ) from error

    def add_listener(self, listener: Callable[[Envelope], None]) -> None:
        """Receive every envelope this broker writes (used by the event bus)."""

        self._listeners.append(listener)

    def _notify(self, *envelopes: Envelope) -> None:
        for envelope in envelopes:
            for listener in list(self._listeners):
                with suppress(Exception):
                    listener(copy.deepcopy(envelope))
        if envelopes:
            self._ring()

    # ------------------------------------------------------------- doorbells

    def _own_doorbell(self) -> Doorbell:
        if self._doorbell is None:
            self._doorbell = Doorbell(kind="waiter")
        return self._doorbell

    @staticmethod
    def _register_tx(tx: StoreTransaction, doorbell: Doorbell) -> None:
        records = [
            item
            for item in (tx.get_extension(DOORBELLS, []) or [])
            if isinstance(item, dict) and item.get("id") != doorbell.id
        ]
        records.append(doorbell.record())
        tx.set_extension(DOORBELLS, records[-MAX_DOORBELLS:])

    def _ring(self) -> None:
        """Wake every other waiting or watching process (best effort)."""

        try:
            records = self._read(lambda: self.file.get_extension(DOORBELLS, [])) or []
        except Exception:
            return
        own = {self._doorbell.id} if self._doorbell else set()
        own |= {watcher.doorbell.id for watcher in self._watchers}
        dead = ring_all([item for item in records if isinstance(item, dict)], skip=own)
        if dead:
            with suppress(Exception), self.transaction() as tx:
                tx.set_extension(
                    DOORBELLS,
                    [
                        item
                        for item in (tx.get_extension(DOORBELLS, []) or [])
                        if isinstance(item, dict) and str(item.get("id")) not in set(dead)
                    ],
                )

    def watch(self, on_change: Callable[[], None]) -> DoorbellWatcher:
        """Call ``on_change`` whenever any process writes approval state."""

        def register(doorbell: Doorbell) -> None:
            with self.transaction() as tx:
                self._register_tx(tx, doorbell)

        watcher = DoorbellWatcher(register, on_change)
        self._watchers.append(watcher)
        return watcher

    def close(self) -> None:
        """Unregister and close this broker's doorbells."""

        ids = {watcher.doorbell.id for watcher in self._watchers}
        if self._doorbell is not None:
            ids.add(self._doorbell.id)
        if ids:
            with suppress(Exception), self.transaction() as tx:
                tx.set_extension(
                    DOORBELLS,
                    [
                        item
                        for item in (tx.get_extension(DOORBELLS, []) or [])
                        if isinstance(item, dict) and item.get("id") not in ids
                    ],
                )
        for watcher in self._watchers:
            watcher.close()
        self._watchers.clear()
        if self._doorbell is not None:
            self._doorbell.close()
            self._doorbell = None

    # ------------------------------------------------------------- requests

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
            risk_level=_risk_level(tier),
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
            risk_level=_risk_level(tier),
            risk_reasons=[f"MagAgent permission tier {int(tier)} requires approval."],
            **kwargs,
        )

    @staticmethod
    def _choices(
        digest: str, *, allow_session: bool, allow_persistent: bool
    ) -> list[Mapping[str, Any]]:
        choices: list[Mapping[str, Any]] = [{"decision": "approve", "scope": "once", "label": "Allow once"}]
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
        return choices

    def _origin(self, origin: Mapping[str, Any]) -> Envelope:
        merged: Envelope = {"harness": "magagent", "project": self.project, **dict(origin)}
        merged["session_id"] = str(merged.get("session_id") or "magent-session")
        return merged

    def remembered_scope(
        self,
        action: Mapping[str, Any],
        *,
        origin: Mapping[str, Any],
        risk_level: str = "medium",
        risk_reasons: list[str] | None = None,
    ) -> str | None:
        """Return the scope of an active grant for ``action`` and receipt the hit.

        Returns ``None`` (and writes nothing) when no active grant matches.
        """

        exact = copy.deepcopy(dict(action))
        with self._lock, self.transaction() as tx:
            written = self._use_grant_tx(
                tx, exact, origin=origin, risk_level=risk_level, risk_reasons=risk_reasons or []
            )
        if written is None:
            return None
        scope, envelopes = written
        self._notify(*envelopes)
        return scope

    def _use_grant_tx(
        self,
        tx: StoreTransaction,
        action: Envelope,
        *,
        origin: Mapping[str, Any],
        risk_level: str,
        risk_reasons: list[str],
    ) -> tuple[str, list[Envelope]] | None:
        digest = action_digest(action)
        session_id = str(origin.get("session_id") or "")
        now = _now()
        grants = tx.get_extension(GRANTS, []) or []
        for grant in grants:
            if (
                isinstance(grant, dict)
                and grant.get("action_digest") == digest
                and grant.get("scope") in {"session", "persistent"}
                and grant_status(grant, now) == "active"
                and (grant.get("scope") == "persistent" or grant.get("session_id") == session_id)
            ):
                envelopes = self._record_grant_hit(
                    tx,
                    grants,
                    grant,
                    action,
                    origin=origin,
                    risk_level=risk_level,
                    risk_reasons=risk_reasons,
                    now=now,
                )
                return str(grant["scope"]), envelopes
        return None

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
        with self._lock, self.transaction() as tx:
            remembered = self._use_grant_tx(
                tx, exact_action, origin=origin, risk_level=risk_level, risk_reasons=risk_reasons
            )
            if remembered is None:
                envelope = tx.add_request(
                    action=exact_action,
                    origin=self._origin(origin),
                    risk={"level": risk_level, "reasons": risk_reasons or ["Protected action."]},
                    choices=self._choices(
                        digest, allow_session=allow_session, allow_persistent=allow_persistent
                    ),
                    ttl=max(1.0, timeout),
                )
                self._register_tx(tx, self._own_doorbell())
                request_id = str(envelope["request"]["id"])
                waiter = _Waiter(
                    envelope=envelope,
                    current_action=current_action or (lambda: exact_action),
                    resolved=threading.Event(),
                )
                self._waiters[request_id] = waiter
                self._publishers[request_id] = publish
        if remembered is not None:
            self._notify(*remembered[1])
            return remembered[0]
        self._notify(envelope)
        publish(copy.deepcopy(envelope))
        resolution = self._await(request_id, waiter, publish, timeout)
        with self._lock:
            self._waiters.pop(request_id, None)
            self._publishers.pop(request_id, None)
        if not resolution:
            return "deny"
        body = resolution["resolution"]
        if body["outcome"] == "approved" and action_digest(waiter.current_action()) != digest:
            return "deny"
        return str(body.get("effective_scope", "deny")) if body["outcome"] == "approved" else "deny"

    def _await(
        self, request_id: str, waiter: _Waiter, publish: Publisher, timeout: float
    ) -> Envelope | None:
        """Wait for a decision from this process (event) or another one (a ring).

        Rings are pushed by whichever process writes the decision; the store is
        re-read only on a ring or every few seconds as a safety net.
        """

        doorbell = self._own_doorbell()
        deadline = time.monotonic() + timeout
        while True:
            if waiter.resolved.is_set():
                return waiter.resolution
            durable = self._read(lambda: self.file.get_resolution(request_id))
            if durable is not None and not waiter.resolved.is_set():
                waiter.resolution = durable
                for listener in list(self._listeners):
                    with suppress(Exception):
                        listener(copy.deepcopy(durable))
                publish(copy.deepcopy(durable))
                return durable
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            doorbell.wait(min(remaining, SAFETY_POLL_SECONDS))
        with suppress(ConflictError, ValueError, UnknownRequestError):
            self.decide(
                request_id,
                decision="deny",
                scope="once",
                actor={"id": "magent.timeout", "type": "policy", "authenticated_by": "authority"},
            )
        return waiter.resolution or self._read(lambda: self.file.get_resolution(request_id))

    def _wait_durable(
        self, request_id: str, timeout: float, cancelled: threading.Event
    ) -> Envelope | None:
        return self._read(
            lambda: self.file.wait_for_resolution(request_id, timeout=timeout, cancelled=cancelled)
        )

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
        with self._lock:
            waiter = self._waiters.get(request_id)
            with self.transaction() as tx:
                pending = tx.get_pending(request_id)
                current = waiter.current_action() if waiter and pending else None
                resolution = tx.decide(
                    request_id,
                    decision=decision,
                    scope=scope,
                    actor=dict(actor),
                    decision_id=decision_id,
                    reviewed_digest=reviewed_digest,
                    current_action=current,
                )
                if (
                    pending is not None
                    and resolution["resolution"]["outcome"] == "approved"
                    and scope in {"session", "persistent"}
                ):
                    grants = tx.get_extension(GRANTS, []) or []
                    grants.append(self._new_grant(pending, scope, resolution, actor=actor))
                    tx.set_extension(GRANTS, grants)
            publisher = self._publishers.get(request_id)
            if waiter and pending is not None:
                waiter.resolution = resolution
        if pending is not None:
            self._notify(resolution)
        if publisher and pending is not None:
            publisher(copy.deepcopy(resolution))
        if waiter:
            waiter.resolved.set()
            if self._doorbell is not None:
                self._doorbell.poke()
        return copy.deepcopy(resolution)

    def record_local_decision(
        self,
        action: Mapping[str, Any],
        *,
        origin: Mapping[str, Any],
        decision: str,
        scope: str,
        actor: Mapping[str, Any],
        risk_level: str = "medium",
        risk_reasons: list[str] | None = None,
        allow_persistent: bool = True,
    ) -> Envelope:
        """Record a decision a local presenter (the terminal) already collected.

        The request and its decision are written in one transaction, so the
        approval log shows the terminal answer like any other, and a
        session/persistent approval becomes a grant with the same expiry,
        listing, revocation and receipts as broker-mediated grants.
        """

        exact = copy.deepcopy(dict(action))
        digest = action_digest(exact)
        with self._lock, self.transaction() as tx:
            requested = tx.add_request(
                action=exact,
                origin=self._origin(origin),
                risk={"level": risk_level, "reasons": risk_reasons or ["Protected action."]},
                choices=self._choices(
                    digest, allow_session=True, allow_persistent=allow_persistent
                ),
            )
            request_id = str(requested["request"]["id"])
            pending = tx.get_pending(request_id)
            resolution = tx.decide(request_id, decision=decision, scope=scope, actor=dict(actor))
            if resolution["resolution"]["outcome"] == "approved" and scope in {
                "session",
                "persistent",
            }:
                grants = tx.get_extension(GRANTS, []) or []
                grants.append(self._new_grant(pending or requested, scope, resolution, actor=actor))
                tx.set_extension(GRANTS, grants)
        self._notify(requested, resolution)
        return copy.deepcopy(resolution)

    # ------------------------------------------------------------------ grants

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
            "source": str(actor.get("authenticated_by") or ""),
            "hits": 0,
        }
        if scope == "persistent" and self.grant_ttl_days > 0:
            created = _parse_timestamp(created_at) or _now()
            grant["expires_at"] = _timestamp(created + timedelta(days=self.grant_ttl_days))
        return grant

    def _record_grant_hit(
        self,
        tx: StoreTransaction,
        grants: list[Any],
        grant: Envelope,
        action: Envelope,
        *,
        origin: Mapping[str, Any],
        risk_level: str,
        risk_reasons: list[str],
        now: datetime,
    ) -> list[Envelope]:
        """Write an AAIS receipt for an action a remembered grant approved.

        The hit is a complete requested/decided/resolved exchange whose decision
        actor is the grant itself, plus a compact ``grant_hits`` entry.
        """

        grant_id = grant_id_for(grant)
        scope = str(grant["scope"])
        digest = str(grant["action_digest"])
        stamp = _timestamp(now)
        requested = tx.add_request(
            action=action,
            origin=self._origin(origin),
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
            created_at=stamp,
        )
        request_id = str(requested["request"]["id"])
        resolution = tx.decide(
            request_id,
            decision="approve",
            scope=scope,
            actor={"id": f"magent.grant:{grant_id}", **_GRANT_ACTOR},
            current_action=action,
        )
        grant["id"] = grant_id
        grant["hits"] = int(grant.get("hits", 0) or 0) + 1
        grant["last_used_at"] = stamp
        tx.set_extension(GRANTS, grants)
        hits = tx.get_extension(GRANT_HITS, []) or []
        hits.append(
            {
                "grant_id": grant_id,
                "request_id": request_id,
                "resolution_id": resolution["resolution"]["id"],
                "action_digest": digest,
                "scope": scope,
                "session_id": str(origin.get("session_id") or ""),
                "occurred_at": stamp,
            }
        )
        tx.set_extension(GRANT_HITS, hits[-GRANT_HIT_LIMIT:])
        return [requested, resolution]

    @staticmethod
    def _action_details(events: list[Envelope], digest: str) -> Envelope:
        for event in reversed(events):
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

        grants = self._read(lambda: self.file.get_extension(GRANTS, [])) or []
        events: list[Envelope] | None = None
        now = _now()
        rows: list[Envelope] = []
        for grant in grants:
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
                if events is None:
                    events = self._read(lambda: self.file.events_after(0).events)
                details = {
                    **details,
                    **self._action_details(events, str(grant.get("action_digest"))),
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
                "source": grant.get("source", "") or ("legacy" if legacy else ""),
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
        with self._lock, self.transaction() as tx:
            grants = tx.get_extension(GRANTS, []) or []
            now = _now()
            known = {grant_id_for(item) for item in grants if isinstance(item, dict)}
            missing = sorted(wanted - known)
            for grant in grants:
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
                tx.set_extension(GRANTS, grants)
        return {"ok": not missing, "revoked": revoked, "missing": missing}

    def grant_hits(self, limit: int = 100) -> list[Envelope]:
        hits = self._read(lambda: self.file.get_extension(GRANT_HITS, [])) or []
        return [copy.deepcopy(item) for item in hits[-max(1, limit) :]]

    # ------------------------------------------------------------ lifecycle

    def cancel_owner(self, **origin: str) -> int:
        matches = [
            request
            for request in self._read(self.file.pending_requests)
            if all(
                str(request.get("request", {}).get("origin", {}).get(key, "")) == value
                for key, value in origin.items()
            )
        ]
        for request in matches:
            with suppress(ConflictError, ValueError):
                self.decide(
                    str(request["request"]["id"]),
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

    def recovery(self) -> Envelope:
        report = self._read(self.file.recovery).to_dict()
        report["guidance"] = (
            "Stopped owners are not restarted. Inspect completed effects before creating a new run."
        )
        return report

    def cancel_orphaned(self) -> list[Envelope]:
        return list(self._read(lambda: self.file.cancel_orphaned(actor_id="magent.recovery")))

    def snapshot(self) -> Envelope:
        return dict(self._read(self.file.snapshot))

    def events_page(self, sequence: int) -> Envelope:
        """Replay with an explicit gap flag (resync from ``snapshot`` on a gap)."""

        return dict(self._read(lambda: self.file.events_after(sequence)).to_dict())

    def events_after(self, sequence: int) -> list[Envelope]:
        return list(self.events_page(sequence)["events"])


def start_stdio_broker(
    store: WorkbenchStore,
    *,
    project: str | Path,
    stream: str,
    out: Any = None,
) -> tuple[ApprovalBroker, Publisher]:
    """Start the AAIS NDJSON decision reader used by headless desktop clients.

    ``out`` is the machine output stream (stdout when omitted). It is captured
    here so envelopes still reach the client when the caller redirects
    ``sys.stdout`` to keep status text off the machine channel.
    """

    broker = ApprovalBroker(store, project=project, stream=stream)
    target = out if out is not None else sys.stdout

    def publish(envelope: Envelope) -> None:
        print(json.dumps(envelope, separators=(",", ":"), default=str), file=target, flush=True)

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
