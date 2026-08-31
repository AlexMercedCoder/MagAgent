"""AAIS authority broker shared by every MagAgent execution surface.

The broker is deliberately independent from HTTP, the terminal, and the graph
runtime.  A presenter receives validated AAIS envelopes and sends a decision
back here; this class remains the authority that persists, revalidates, and
atomically resolves the exact action before the waiting tool may continue.
"""

from __future__ import annotations

import copy
import json
import signal
import sys
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aais import (
    ApprovalStore,
    ConflictError,
    action_digest,
    create_decision,
    create_request,
    validate,
)

from magent.workbench_store import WorkbenchStore

Envelope = dict[str, Any]
Publisher = Callable[[Envelope], None]
CurrentAction = Callable[[], Mapping[str, Any]]


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
    ) -> None:
        self.store = store
        self.project = str(Path(project).resolve())
        self.stream = stream
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
        state = self.store.read(self.STORE_NAME, self._empty())
        return state if isinstance(state, dict) else self._empty()

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
        with self._lock:
            state = self._state()
            remembered = next(
                (
                    str(item["scope"])
                    for item in state.get("grants", [])
                    if item.get("action_digest") == digest
                    and item.get("scope") in {"session", "persistent"}
                    and (
                        item.get("scope") == "persistent"
                        or item.get("session_id") == str(origin.get("session_id") or "")
                    )
                ),
                None,
            )
            if remembered:
                return remembered
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
            state.setdefault("events", []).append(envelope)
            state["events"] = state["events"][-1000:]
            self.store.write(self.STORE_NAME, state)
            waiter = _Waiter(
                envelope=envelope,
                current_action=current_action or (lambda: exact_action),
                resolved=threading.Event(),
            )
            self._waiters[request_id] = waiter
            self._publishers[request_id] = publish
        publish(copy.deepcopy(envelope))
        if not waiter.resolved.wait(timeout):
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
        with self._lock:
            resolution = waiter.resolution
            self._waiters.pop(request_id, None)
            self._publishers.pop(request_id, None)
        if not resolution:
            return "deny"
        body = resolution["resolution"]
        return str(body.get("effective_scope", "deny")) if body["outcome"] == "approved" else "deny"

    def decide(
        self,
        request_id: str,
        *,
        decision: str,
        scope: str,
        actor: Mapping[str, Any],
        decision_id: str | None = None,
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
            state.setdefault("events", []).append(resolution)
            if resolution["resolution"]["outcome"] == "approved" and scope in {
                "session",
                "persistent",
            }:
                state.setdefault("grants", []).append(
                    {
                        "action_digest": pending["request"]["action_digest"],
                        "scope": scope,
                        "session_id": str(
                            pending["request"].get("origin", {}).get("session_id") or ""
                        ),
                        "created_at": resolution["occurred_at"],
                    }
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

    def snapshot(self) -> Envelope:
        with self._lock:
            state = self._state()
            machine = ApprovalStore(last_sequence=int(state.get("sequence", 0)))
            for envelope in state.get("pending", {}).values():
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
                    envelope = json.loads(line)
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
