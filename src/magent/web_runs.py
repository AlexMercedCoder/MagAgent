"""Durable turns for the local Web UI.

A turn used to run on the HTTP request thread that started it. Close the tab
mid-reply and the work died with the socket: the assistant's answer was never
recorded, the conversation kept the user's message with no response, and there
was no way to stop a turn that was going nowhere short of killing the server.

A turn is now a run: it executes on its own thread, appends every event to an
append-only log, and finishes whether or not anyone is watching. The browser
streams that log from a cursor, so reconnecting replays what it missed instead
of losing it, and a run can be cancelled without touching the process.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from aais import ConflictError

from magent.approval_broker import ApprovalBroker

# Runs are held in memory for reattachment after a reload, not as history: the
# conversation store is what persists. Keeping every run of a long session would
# grow without bound, so finished ones are evicted oldest-first.
MAX_RETAINED_RUNS = 50

TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})

# How long a reader blocks before re-checking. It only bounds how quickly a
# disconnected socket is noticed, not how quickly a chunk is delivered.
STREAM_WAIT_SECONDS = 1.0


class RunCancelled(Exception):
    """Raised inside a run's thread when cancellation is observed."""


# How long a run waits for a human to answer an approval before giving up. A
# browser that closed is indistinguishable from one that is thinking, so the
# turn must not block a worker thread forever.
APPROVAL_TIMEOUT_SECONDS = 300


class ApprovalRequest:
    """One tool waiting on a decision from whoever is watching the run."""

    def __init__(self, request_id: str, description: str, tier: int) -> None:
        self.request_id = request_id
        self.description = description
        self.tier = tier
        self.approved = False
        self.decided = threading.Event()

    def as_event(self) -> dict[str, Any]:
        return {
            "type": "approval.requested",
            "request_id": self.request_id,
            "description": self.description,
            "tier": self.tier,
        }


class Run:
    """One turn, its event log, and its cancellation flag."""

    def __init__(self, conversation_id: str, broker: ApprovalBroker | None = None) -> None:
        self.id = f"run_{uuid.uuid4().hex[:16]}"
        self.conversation_id = conversation_id
        self.state = "running"
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.error = ""
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        # Waiters block on this instead of polling, so a streaming reader sees a
        # chunk as soon as it is appended.
        self._changed = threading.Condition(self._lock)
        self._cancel = threading.Event()
        self.approval: ApprovalRequest | None = None
        self.broker = broker

    # -- writing (run thread) ------------------------------------------------

    def append(self, event: dict[str, Any]) -> None:
        with self._changed:
            self._events.append(event)
            self._changed.notify_all()

    def finish(self, state: str, error: str = "") -> None:
        with self._changed:
            self.state = state
            self.error = error
            self.finished_at = time.time()
            self._changed.notify_all()

    # -- cancellation --------------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()
        # A run parked on an approval would otherwise sit until the timeout,
        # which makes cancelling look broken for exactly the turns most likely
        # to need it.
        waiting = self.approval
        if waiting is not None:
            waiting.approved = False
            waiting.decided.set()
        if self.broker is not None:
            self.broker.cancel_owner(run_id=self.id)
        with self._changed:
            self._changed.notify_all()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        """Cooperative cancellation check, called between units of work."""
        if self._cancel.is_set():
            raise RunCancelled()

    # -- approvals -----------------------------------------------------------

    def request_approval(
        self, description: str, tier: int, action: dict[str, Any] | None = None
    ) -> bool:
        """Ask whoever is watching, and block this run until they answer.

        The Web UI ran with permissions non-interactive, so every tool above
        the auto-approve threshold was refused outright and the agent could not
        do real work. The decision now goes to the browser through the same
        event log everything else travels on.
        """
        if self.broker is not None:
            common = dict(
                origin={
                    "session_id": self.conversation_id,
                    "run_id": self.id,
                },
                publish=self.append,
                timeout=APPROVAL_TIMEOUT_SECONDS,
                allow_session=True,
                allow_persistent=str(description).lstrip().startswith("Run:"),
            )
            decision = self.broker.request_prompt(description, tier, action, **common)
            return decision != "deny"
        request = ApprovalRequest(f"ask_{uuid.uuid4().hex[:12]}", description, int(tier))
        self.approval = request
        self.append(request.as_event())
        try:
            if not request.decided.wait(APPROVAL_TIMEOUT_SECONDS):
                # Unanswered is not approved. A tab that closed must not leave a
                # tool authorised by default.
                self.append(
                    {
                        "type": "approval.resolved",
                        "request_id": request.request_id,
                        "approved": False,
                        "reason": "timeout",
                    }
                )
                return False
            # A cancel while waiting must not be swallowed by the approval.
            self.raise_if_cancelled()
            return request.approved
        finally:
            self.approval = None

    def decide_approval(
        self,
        request_id: str,
        approved: bool,
        scope: str = "once",
        *,
        actor_id: str = "local-user",
    ) -> bool:
        if self.broker is not None:
            try:
                self.broker.decide(
                    request_id,
                    decision="approve" if approved else "deny",
                    scope=scope if approved else "once",
                    actor={
                        "id": actor_id,
                        "type": "human",
                        "authenticated_by": "magent-loopback-token",
                    },
                )
                return True
            except (ValueError, ConflictError):
                return False
        request = self.approval
        if request is None or request.request_id != request_id or request.decided.is_set():
            return False
        request.approved = bool(approved)
        request.decided.set()
        self.append(
            {
                "type": "approval.resolved",
                "request_id": request_id,
                "approved": bool(approved),
                "reason": "answered",
            }
        )
        return True

    # -- reading (any thread) ------------------------------------------------

    @property
    def cursor(self) -> int:
        with self._lock:
            return len(self._events)

    def since(self, after: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events[max(0, after) :])

    def wait(self, after: int, timeout: float) -> None:
        """Block until there is something past `after`, or the run ends."""
        with self._changed:
            if len(self._events) > max(0, after) or self.state in TERMINAL_STATES:
                return
            self._changed.wait(timeout)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "conversation_id": self.conversation_id,
                "state": self.state,
                "cursor": len(self._events),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "awaiting_approval": (
                    self.approval.as_event() if self.approval is not None else None
                ),
            }


class RunStore:
    """Every run this server has started, newest last."""

    def __init__(self, broker: ApprovalBroker | None = None) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self.broker = broker

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return newest run snapshots for the browser run center."""
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda run: run.started_at, reverse=True)
        return [run.snapshot() for run in runs[: max(1, min(int(limit), 500))]]

    def active_for(self, conversation_id: str) -> Run | None:
        """The run a reloading browser should reattach to.

        A reconnecting tab knows its conversation, not the run id it lost, so
        the lookup has to work from the conversation. A finished run still
        counts: the reply may have arrived while the tab was gone.
        """
        with self._lock:
            candidates = [
                run for run in self._runs.values() if run.conversation_id == conversation_id
            ]
        return max(candidates, key=lambda run: run.started_at) if candidates else None

    def start(self, conversation_id: str, work: Callable[[Run], None]) -> Run:
        """Begin a run on its own thread and return immediately.

        `work` receives the run and is responsible for appending events. It runs
        to completion even if every reader disconnects, which is the point: the
        reply is recorded whether or not a tab is open to see it.
        """
        run = Run(conversation_id, self.broker)
        with self._lock:
            self._runs[run.id] = run
            self._evict()

        def execute() -> None:
            try:
                work(run)
            except RunCancelled:
                run.append({"type": "cancelled"})
                run.finish("cancelled")
            except Exception as problem:  # noqa: BLE001 - reported through the log
                from magent.webui_errors import describe

                friendly = describe(problem)
                run.append({"type": "error", **friendly.as_event()})
                run.finish("failed", friendly.as_message())
            else:
                if run.state not in TERMINAL_STATES:
                    run.finish("succeeded")

        threading.Thread(target=execute, name=f"magent-{run.id}", daemon=True).start()
        return run

    def cancel(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        if run is None:
            return {"ok": False, "error": f"No run called {run_id}."}
        if run.state in TERMINAL_STATES:
            # Cancelling something already finished is not a failure; saying so
            # is more useful than an error the user cannot act on.
            return {"ok": True, "state": run.state, "note": "That run had already finished."}
        run.cancel()
        return {"ok": True, "state": "cancelling"}

    def _evict(self) -> None:
        """Drop the oldest finished runs once the cap is passed."""
        if len(self._runs) <= MAX_RETAINED_RUNS:
            return
        finished = sorted(
            (run for run in self._runs.values() if run.state in TERMINAL_STATES),
            key=lambda run: run.finished_at or run.started_at,
        )
        # Never evict a running turn, however old: it still has a reader coming.
        for run in finished[: len(self._runs) - MAX_RETAINED_RUNS]:
            self._runs.pop(run.id, None)
