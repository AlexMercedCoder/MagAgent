"""Durable AGS level-3 execution over MagAgent's existing agent loop."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from magent.agraph.criteria import CriterionResult, evaluate_criteria
from magent.agraph.document import GraphDocument, load_graph
from magent.agraph.events import GRAPH_EVENT_SCHEMA_VERSION, graph_event
from magent.agraph.expressions import (
    AgxEvaluationError,
    evaluate_expression,
    resolve_reference,
    resolve_value,
)
from magent.agraph.mappings import tool_requirement, tools_for_requirement
from magent.agraph.output import begin_output_collection, end_output_collection
from magent.agraph.plan import effective_edges, plan_graph
from magent.agraph.record import new_run_record, now_iso, validate_run_record
from magent.agraph.routing import Route, route_for_node
from magent.agraph.runtime_context import (
    GraphToolPolicy,
    reset_graph_tool_policy,
    set_graph_tool_policy,
)
from magent.agraph.schedule import blocking_reasons, edge_table, propagate_skips, ready_nodes
from magent.agraph.validate import validate_graph
from magent.sandbox import graph_workspace
from magent.task_runtime import TaskRuntime, TaskState
from magent.workbench_store import WorkbenchStore

AgentRunner = Callable[[str, str, Route, str], Awaitable[Any]]
ApprovalCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]
EventSink = Callable[[dict[str, Any]], None]


class GraphRunError(RuntimeError):
    def __init__(self, message: str, code: str = "RT001"):
        self.code = code
        super().__init__(f"{code}: {message}")


class GraphExecutor:
    """Execute one validated graph and emit a portable run record."""

    def __init__(
        self,
        *,
        username: str,
        config: Any,
        project: str | Path = ".",
        store: WorkbenchStore | None = None,
        agent_runner: AgentRunner | None = None,
        approval: ApprovalCallback | None = None,
        assume_yes: bool = False,
        root_task_id: str = "",
        compatibility_completed_state: bool = False,
        profile: Any | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.username = username
        self.config = config
        self.project = Path(project).expanduser().resolve()
        self.store = store or WorkbenchStore(username)
        self.runtime = TaskRuntime(self.store)
        self.agent_runner = agent_runner or self._default_agent_runner
        self.approval = approval
        self.assume_yes = assume_yes
        self._root_task_id = root_task_id
        self.compatibility_completed_state = compatibility_completed_state
        self.profile = profile
        self.event_sink = event_sink
        self._active_profile: ContextVar[Any | None] = ContextVar(
            "magent_agraph_active_profile", default=profile
        )
        self._profile_cache: dict[str, Any] = {}
        self._record: dict[str, Any] = {}
        self._started = 0.0
        self._document: GraphDocument | None = None
        self._node_records: dict[str, dict[str, Any]] = {}
        self._node_tasks: dict[str, str] = {}
        self._completed_for_compensation: list[tuple[str, dict[str, Any]]] = []
        self._resume_nodes: dict[str, dict[str, Any]] = {}
        self._workspace: ContextVar[Path] = ContextVar(
            "magent_agraph_workspace", default=self.project
        )
        self._agent_steps: ContextVar[int] = ContextVar("magent_agraph_agent_steps", default=0)
        # Per-node usage, so budgets are not charged for sibling nodes.
        self._node_usage: ContextVar[dict[str, Any] | None] = ContextVar(
            "magent_agraph_node_usage", default=None
        )
        # Guards alternate_node fallback recursion.
        self._fallback_chain: list[str] = []
        self._composition_depth: ContextVar[int] = ContextVar(
            "magent_agraph_composition_depth", default=0
        )
        from magent.plugins import load_external_graph_checkers

        load_external_graph_checkers()

    async def run(
        self,
        source: str | Path | dict[str, Any] | GraphDocument,
        *,
        params: dict[str, Any] | None = None,
        dry_run: bool = False,
        resume_record: dict[str, Any] | None = None,
        force: bool = False,
        retry_nodes: set[str] | None = None,
    ) -> dict[str, Any]:
        document = source if isinstance(source, GraphDocument) else load_graph(source)
        report = validate_graph(document)
        if not report.ok:
            raise GraphRunError(
                "; ".join(f"{item.code} {item.message}" for item in report.errors[:8]), "AG001"
            )
        plan = plan_graph(document)
        if dry_run:
            return {"ok": True, "dry_run": True, "plan": plan.as_dict()}
        bound_params = _bind_params(document.data, params or {})
        if resume_record and resume_record.get("graph_digest") != document.digest and not force:
            raise GraphRunError("graph digest changed since the saved run", "RT053")
        self._preflight(document, plan)
        self._document = document
        self._started = time.monotonic()
        run_id = str((resume_record or {}).get("run_id") or f"agraph_{uuid.uuid4().hex[:16]}")
        self._record = new_run_record(
            document, run_id, _redact_values(document.data.get("params") or {}, bound_params)
        )
        self._record["metadata"] = {
            "source_path": str(document.path) if document.path else "",
            "project": str(self.project),
            "graph_snapshot": json.loads(json.dumps(document.data)),
            "event_schema_version": GRAPH_EVENT_SCHEMA_VERSION,
        }
        resume_mode = str((document.data.get("policy") or {}).get("resume", "resume_incomplete"))
        invalidated = _retry_closure(document.data, retry_nodes or set()) if retry_nodes else set()
        if retry_nodes:
            unknown = sorted(set(retry_nodes) - set(document.data.get("nodes") or {}))
            if unknown:
                raise GraphRunError(f"retry nodes do not exist: {', '.join(unknown)}", "RT054")
            self._record["metadata"]["retry_nodes"] = sorted(retry_nodes)
            self._record["metadata"]["invalidated_nodes"] = sorted(invalidated)
        if resume_record and resume_mode != "restart":
            self._resume_nodes = {
                str(item.get("scope_path") or item.get("node_id")): item
                for item in resume_record.get("nodes") or []
                if item.get("status") == "succeeded"
                and not _contains_redaction(item.get("outputs"))
                and str(item.get("scope_path") or item.get("node_id")) not in invalidated
            }
        if self._root_task_id:
            root_task = self.runtime.get(self._root_task_id)
            if root_task is None:
                raise GraphRunError(f"parent task {self._root_task_id!r} does not exist", "RT052")
            if root_task["state"] in {"completed", "succeeded", "failed", "cancelled", "skipped"}:
                self.runtime.retry(self._root_task_id, reason="Agentic Graph retry")
                root_task = self.runtime.get(self._root_task_id)
            if root_task and root_task["state"] in {"waiting", "blocked"}:
                self.runtime.resume(self._root_task_id, reason="Agentic Graph execution started")
            elif root_task and root_task["state"] != "running":
                self.runtime.transition(
                    self._root_task_id, "running", reason="Agentic Graph execution started"
                )
        else:
            self._root_task_id = self.runtime.create(
                "agentic_graph",
                document.data.get("title", document.graph_id),
                project=self.project,
                state="running",
                permission_policy=str(getattr(self.config, "permission_mode", "balanced")),
                metadata={
                    "run_id": run_id,
                    "graph_id": document.graph_id,
                    "graph_digest": document.digest,
                },
            )["id"]
        self.runtime.update_context(
            self._root_task_id,
            metadata={
                "run_id": run_id,
                "graph_id": document.graph_id,
                "graph_digest": document.digest,
                "source_path": str(document.path) if document.path else "",
                "event_schema_version": GRAPH_EVENT_SCHEMA_VERSION,
            },
        )
        self._record["metadata"]["execution_task_id"] = self._root_task_id
        self.store.append("graph_runs", self._record)
        self._emit("graph.started", state="running", summary="Graph execution started.")
        try:
            scope = self._base_scope(document.data, bound_params)
            statuses, outputs = await self._run_scope(document.data, scope, scope_path="")
            self._record["edges_taken"] = [
                {
                    "from": edge["from"],
                    "to": edge["to"],
                    "kind": edge["kind"],
                    "active": bool(edge["active"]),
                    "when_result": edge["active"],
                    "at": now_iso(),
                }
                for edge in edge_table(document.data, statuses, scope)
                if edge["active"] is not None
            ]
            self._record["outputs"] = _redact_values(
                document.data.get("outputs") or {},
                self._resolve_graph_outputs(document.data, scope),
            )
            graph_success = document.data.get("success") or {}
            if graph_success.get("criteria"):
                passed, results = await self._criteria(
                    graph_success.get("criteria") or [],
                    self._record["outputs"],
                    scope,
                    mode=str(graph_success.get("mode", "all")),
                    count=int(graph_success.get("count", 1) or 1),
                )
                self._record["graph_success"] = {
                    "passed": passed,
                    "mode": graph_success.get("mode", "all"),
                    "results": [item.as_dict() for item in results],
                }
            else:
                passed = all(status in {"succeeded", "skipped"} for status in statuses.values())
            failed = (
                any(status in {"failed", "blocked", "cancelled"} for status in statuses.values())
                or not passed
            )
            self._finish("failed" if failed else "succeeded")
            if failed:
                await self._compensate(scope)
                self.runtime.transition(
                    self._root_task_id, "failed", reason="Graph execution failed"
                )
            else:
                self.runtime.transition(
                    self._root_task_id,
                    "completed" if self.compatibility_completed_state else "succeeded",
                    reason="Graph execution succeeded",
                )
            self._finalize_root_task(failed)
        except asyncio.CancelledError:
            self._finish("cancelled")
            self.runtime.transition(
                self._root_task_id, "cancelled", reason="Graph execution cancelled"
            )
            self._finalize_root_task(
                True,
                error="Graph execution was cancelled.",
                error_code="GRAPH_CANCELLED",
            )
            # Persist before re-raising: the record was left saying "running"
            # forever, because the raise skipped the write below.
            with contextlib.suppress(Exception):
                self._persist_record()
            self._emit(
                "graph.completed",
                state="cancelled",
                summary="Graph execution was cancelled.",
                error_code="GRAPH_CANCELLED",
            )
            raise
        except Exception as exc:
            self._diagnostic(getattr(exc, "code", "RT001"), "error", str(exc))
            await self._compensate(self._base_scope(document.data, bound_params))
            self._finish("failed")
            with contextlib.suppress(Exception):
                self.runtime.transition(self._root_task_id, "failed", reason=str(exc))
            self._finalize_root_task(True, error=str(exc), error_code=getattr(exc, "code", "RT001"))
        self._persist_record()
        validate_run_record(self._record)
        self._emit(
            "graph.completed",
            state=self._record["status"],
            summary=str(
                (self._record.get("metadata", {}).get("x-magagent-summary") or {}).get("text", "")
            ),
            error_code="" if self._record["status"] == "succeeded" else "GRAPH_RUN_FAILED",
        )
        return {
            "ok": self._record["status"] == "succeeded",
            "run": self._record,
            "task_id": self._root_task_id,
        }

    async def _run_scope(
        self,
        document: dict[str, Any],
        scope: dict[str, Any],
        *,
        scope_path: str,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        nodes = document.get("nodes") or {}
        statuses = {node_id: "pending" for node_id in nodes}
        outputs: dict[str, dict[str, Any]] = {}
        scope["nodes"] = {}
        scope["_statuses"] = statuses
        for node_id in nodes:
            full_id = f"{scope_path}.{node_id}".strip(".")
            previous = self._resume_nodes.get(full_id)
            if previous:
                statuses[node_id] = "succeeded"
                outputs[node_id] = dict(previous.get("outputs") or {})
                scope["nodes"][node_id] = {"outputs": outputs[node_id], "status": "succeeded"}
                self._record["nodes"].append(previous)
                self._ensure_node_task(
                    full_id,
                    nodes[node_id],
                    state="succeeded",
                    summary=str(
                        previous.get("x-magagent-summary")
                        or "Reused from the prior successful run."
                    ),
                )
            else:
                reasons = blocking_reasons(document, node_id, statuses, scope)
                self._ensure_node_task(full_id, nodes[node_id], state="ready", blocked_by=reasons)
        max_parallel = min(
            max(1, int((document.get("constraints") or {}).get("max_parallel_nodes", 1) or 1)),
            max(1, int(getattr(self.config, "max_parallel_subagents", 1))),
        )
        groups_running: set[str] = set()
        while any(status == "pending" for status in statuses.values()):
            await self._await_runtime_control()
            self._check_global_budget(document)
            skipped = propagate_skips(document, statuses, scope)
            for node_id in skipped:
                full_id = f"{scope_path}.{node_id}".strip(".")
                self._terminalize_nonexecuted(
                    full_id,
                    nodes[node_id],
                    "skipped",
                    "No dependency route became active for this job.",
                    "GRAPH_ROUTE_SKIPPED",
                )
            candidates = ready_nodes(document, statuses, scope)
            selected = []
            for node_id in candidates:
                group = str((nodes[node_id].get("constraints") or {}).get("concurrency_group", ""))
                if group and group in groups_running:
                    continue
                selected.append(node_id)
                if group:
                    groups_running.add(group)
                if len(selected) >= max_parallel:
                    break
            if not selected:
                if all(status != "pending" for status in statuses.values()):
                    break
                unresolved = [
                    node_id for node_id, status in statuses.items() if status == "pending"
                ]
                for node_id in unresolved:
                    statuses[node_id] = "blocked"
                    full_id = f"{scope_path}.{node_id}".strip(".")
                    reasons = blocking_reasons(document, node_id, statuses, scope)
                    message = (
                        "; ".join(item["message"] for item in reasons)
                        or "Node cannot become ready."
                    )
                    self._terminalize_nonexecuted(
                        full_id, nodes[node_id], "blocked", message, "RT021", blocked_by=reasons
                    )
                    self._diagnostic("RT021", "error", message, node_id=node_id)
                break
            results = await asyncio.gather(
                *(
                    self._execute_node(node_id, nodes[node_id], scope, scope_path)
                    for node_id in selected
                ),
                return_exceptions=True,
            )
            for node_id, result in zip(selected, results, strict=True):
                group = str((nodes[node_id].get("constraints") or {}).get("concurrency_group", ""))
                groups_running.discard(group)
                if isinstance(result, BaseException):
                    statuses[node_id] = "failed"
                    # Record the failure in scope too: downstream expressions
                    # like `nodes.X.status == "failed"` used to raise RT020
                    # because the node was never added at all.
                    outputs[node_id] = {}
                    scope["nodes"][node_id] = {"outputs": {}, "status": "failed"}
                    self._diagnostic(
                        getattr(result, "code", "RT001"), "error", str(result), node_id=node_id
                    )
                    full_id = f"{scope_path}.{node_id}".strip(".")
                    if full_id not in self._node_records:
                        self._terminalize_nonexecuted(
                            full_id,
                            nodes[node_id],
                            "failed",
                            str(result),
                            getattr(result, "code", "RT001"),
                        )
                    continue
                status, node_outputs = result
                statuses[node_id] = status
                outputs[node_id] = node_outputs
                scope["nodes"][node_id] = {"outputs": node_outputs, "status": status}
            policy = document.get("policy") or {}
            if policy.get("on_node_failure", "halt") == "halt" and any(
                status == "failed" for status in statuses.values()
            ):
                for node_id, status in statuses.items():
                    if status == "pending":
                        statuses[node_id] = "skipped"
                        full_id = f"{scope_path}.{node_id}".strip(".")
                        self._terminalize_nonexecuted(
                            full_id,
                            nodes[node_id],
                            "skipped",
                            "Skipped because an upstream job failed and the graph failure policy is halt.",
                            "GRAPH_UPSTREAM_FAILED",
                        )
                break
        return statuses, outputs

    async def _run_nested_scope(
        self,
        document: dict[str, Any],
        scope: dict[str, Any],
        *,
        scope_path: str,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        depth = self._composition_depth.get() + 1
        limit = int(
            (
                ((self._document.data if self._document else {}).get("constraints") or {}).get(
                    "max_subgraph_depth", 5
                )
            )
            or 5
        )
        if depth > limit:
            raise GraphRunError(
                f"composition depth {depth} exceeds max_subgraph_depth {limit}", "RT030"
            )
        token = self._composition_depth.set(depth)
        try:
            return await self._run_scope(document, scope, scope_path=scope_path)
        finally:
            self._composition_depth.reset(token)

    async def _execute_node(
        self,
        node_id: str,
        node: dict[str, Any],
        scope: dict[str, Any],
        scope_path: str,
    ) -> tuple[str, dict[str, Any]]:
        full_id = f"{scope_path}.{node_id}".strip(".")
        await self._await_runtime_control()
        if node.get("when"):
            try:
                if not bool(evaluate_expression(str(node["when"]), scope)):
                    self._terminalize_nonexecuted(
                        full_id,
                        node,
                        "skipped",
                        "The node guard condition evaluated to false.",
                        "GRAPH_GUARD_FALSE",
                    )
                    return "skipped", {}
            except AgxEvaluationError as exc:
                policy = (self._document.data.get("policy") if self._document else {}) or {}
                if policy.get("on_expression_error", "fail") == "skip_node":
                    self._terminalize_nonexecuted(
                        full_id,
                        node,
                        "skipped",
                        f"The node guard could not be evaluated: {exc}",
                        "RT020",
                    )
                    return "skipped", {}
                raise GraphRunError(str(exc), "RT020") from exc
        resolved_inputs = self._resolve_inputs(node, scope)
        route = route_for_node(self.config, node) if node.get("type", "task") != "gate" else None
        self._enforce_requirements(node)
        self._enforce_node_constraints(node)
        task_id = self._ensure_node_task(full_id, node, state="ready")
        task = self.runtime.get(task_id) or {"id": task_id, "attempt": 1}
        self.runtime.transition(task["id"], "running", reason="Graph node started")
        self._emit_node(
            "node.started",
            full_id,
            node,
            "running",
            task_id=task["id"],
            attempt=int(task.get("attempt", 1)),
        )
        attempts: list[dict[str, Any]] = []
        human_events: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {}
        failure = node.get("failure") or {}
        retry = failure.get("retry") or {}
        maximum = max(1, int(retry.get("max_attempts", 1) or 1))
        feedback = ""
        status = "failed"
        files_changed: list[str] = []
        response_summary = ""
        for attempt_number in range(1, maximum + 1):
            await self._await_runtime_control()
            self._record["usage"]["node_executions"] += 1
            usage_before = dict(self._record["usage"])
            started = now_iso()
            error = ""
            # Reset per attempt: a failed retry used to return whatever the
            # previous attempt had produced.
            outputs = {}
            node_usage_token = self._node_usage.set({})
            criteria_results: list[CriterionResult] = []
            policy_token = set_graph_tool_policy(self._tool_policy(node, scope, full_id))
            try:
                isolation = str((node.get("constraints") or {}).get("isolation", "shared"))
                # Open the workspace relative to the *current* workspace, not
                # the project root: children of an isolated node used to
                # execute against the real project tree.
                base = self._workspace.get()
                with graph_workspace(base, isolation) as workspace:
                    workspace_token = self._workspace.set(workspace)
                    try:
                        await self._checkpoint(node, "before_start", scope, human_events)
                        outputs = await self._run_node_body(
                            full_id, node, resolved_inputs, scope, route, task["id"], feedback
                        )
                        files_changed = [
                            str(item) for item in outputs.pop("_magent_files_changed", [])
                        ]
                        response_summary = str(outputs.pop("_magent_summary", ""))
                        forced_status = str(outputs.pop("_status", ""))
                        self._enforce_usage_budgets(node, usage_before)
                        await self._checkpoint(
                            node,
                            "after_outputs",
                            {**scope, "self": {"outputs": outputs}},
                            human_events,
                        )
                        success = node.get("success") or {}
                        passed, criteria_results = await self._criteria(
                            success.get("criteria") or [],
                            outputs,
                            scope,
                            mode=str(success.get("mode", "all")),
                            count=int(success.get("count", 1) or 1),
                        )
                        required_outputs = {
                            name
                            for name, spec in (node.get("outputs") or {}).items()
                            if spec.get("required", True)
                        }
                        missing = sorted(required_outputs - outputs.keys())
                        if missing:
                            passed = False
                            error = f"missing required outputs: {', '.join(missing)}"
                        status = forced_status or ("succeeded" if passed else "criteria_failed")
                    finally:
                        self._workspace.reset(workspace_token)
            except TimeoutError:
                status, error = "timeout", "node exceeded max_wall_clock_seconds"
            except Exception as exc:
                status, error = "failed", str(exc)
            finally:
                reset_graph_tool_policy(policy_token)
                self._node_usage.reset(node_usage_token)
            attempts.append(
                {
                    "attempt": attempt_number,
                    "status": status
                    if status
                    in {
                        "succeeded",
                        "failed",
                        "timeout",
                        "budget_exceeded",
                        "criteria_failed",
                        "cancelled",
                    }
                    else "failed",
                    "started_at": started,
                    "finished_at": now_iso(),
                    "routed": route.as_dict() if route else None,
                    "success": {
                        "passed": status == "succeeded",
                        "mode": (node.get("success") or {}).get("mode", "all"),
                        "results": [item.as_dict() for item in criteria_results],
                    },
                    "usage": _usage_delta(usage_before, self._record["usage"]),
                    "error": error,
                }
            )
            attempts[-1] = {
                key: value
                for key, value in attempts[-1].items()
                if value is not None and value != ""
            }
            if status == "succeeded":
                break
            feedback = _failed_feedback(criteria_results, error)
            failure_class = _failure_class(status, error)
            retry_on = set(retry.get("retry_on") or ["transient", "tool_error", "criteria_failed"])
            if "any" not in retry_on and failure_class not in retry_on:
                break
            if attempt_number < maximum:
                await asyncio.sleep(_retry_delay(retry, attempt_number))
        final = (
            status
            if status in {"succeeded", "skipped", "awaiting_human"}
            else await self._fallback(node_id, node, outputs, scope)
        )
        if final == "succeeded":
            self.runtime.transition(task["id"], "validating", reason="Node criteria evaluated")
            self.runtime.transition(
                task["id"],
                "completed" if self.compatibility_completed_state else "succeeded",
                reason="Node succeeded",
            )
            self._completed_for_compensation.append((node_id, node))
        elif final == "skipped":
            self.runtime.transition(task["id"], "skipped", reason="Node fallback skipped execution")
        elif final == "awaiting_human":
            self.runtime.transition(task["id"], "awaiting_human", reason="Human action required")
        else:
            self.runtime.transition(
                task["id"], "failed", reason=attempts[-1].get("error", "Node failed")
            )
            last_error = str(attempts[-1].get("error", "Node failed"))
            code_match = re.search(r"\b((?:RT|AG)\d{3})\b", last_error)
            self._diagnostic(
                code_match.group(1) if code_match else "RT001", "error", last_error, node_id=full_id
            )
        summary = _node_summary(node, final, outputs, attempts, response_summary)
        error_code = _error_code(str(attempts[-1].get("error", ""))) if attempts else ""
        self.runtime.update_context(
            task["id"],
            usage=_sum_usage(attempts),
            files_changed=files_changed,
            final_audit={
                "ok": final == "succeeded",
                "summary": summary,
                "error_code": error_code,
                "error": str(attempts[-1].get("error", "")) if attempts else "",
            },
            metadata={
                "summary": summary,
                "result_summary": summary,
                "dependencies": list(node.get("depends_on") or []),
                "agent_profile": str(node.get("x-magagent-profile") or ""),
            },
        )
        self._append_node_record(
            full_id,
            node,
            final,
            resolved_inputs,
            attempts,
            outputs,
            human_events,
            summary=summary,
            files_changed=files_changed,
            error_code=error_code,
        )
        self._emit_node(
            "node.completed",
            full_id,
            node,
            final,
            task_id=task["id"],
            attempt=len(attempts),
            summary=summary,
            error_code=error_code,
            error=str(attempts[-1].get("error", "")) if attempts else "",
            files_changed=files_changed,
            usage=_sum_usage(attempts),
        )
        return final, outputs

    async def _await_runtime_control(self) -> None:
        """Honor durable pause/cancel state at safe graph and node boundaries."""
        while self._root_task_id:
            task = self.runtime.get(self._root_task_id)
            if not task:
                return
            state = str(task.get("state") or "")
            if state == "cancelled":
                raise asyncio.CancelledError
            if state != "waiting":
                return
            await asyncio.sleep(0.25)

    async def _run_node_body(
        self,
        full_id: str,
        node: dict[str, Any],
        inputs: dict[str, Any],
        scope: dict[str, Any],
        route: Route | None,
        task_id: str,
        feedback: str,
    ) -> dict[str, Any]:
        node_type = node.get("type", "task")
        timeout = float((node.get("constraints") or {}).get("max_wall_clock_seconds", 0) or 0)
        coroutine: Awaitable[dict[str, Any]]
        if node_type == "task":
            coroutine = self._run_task(full_id, node, inputs, route, task_id, feedback)
        elif node_type == "decision":
            coroutine = self._run_decision(full_id, node, inputs, scope, route, task_id)
        elif node_type == "gate":
            coroutine = self._run_gate(full_id, node, scope)
        elif node_type == "loop":
            coroutine = self._run_loop(full_id, node, inputs, scope)
        elif node_type == "map":
            coroutine = self._run_map(full_id, node, inputs, scope)
        elif node_type == "subgraph":
            coroutine = self._run_subgraph(full_id, node, inputs, scope)
        else:
            raise GraphRunError(f"unsupported node type {node_type!r}", "AG303")
        profile_token = self._active_profile.set(self._profile_for_node(node))
        try:
            return (
                await asyncio.wait_for(coroutine, timeout=timeout) if timeout else await coroutine
            )
        finally:
            self._active_profile.reset(profile_token)

    async def _run_task(
        self,
        full_id: str,
        node: dict[str, Any],
        inputs: dict[str, Any],
        route: Route | None,
        task_id: str,
        feedback: str,
    ) -> dict[str, Any]:
        if route is None:
            raise GraphRunError("task node has no route", "RT011")
        prompt = _node_prompt(node, inputs, feedback)
        outputs, token = begin_output_collection()
        try:
            response = await self.agent_runner(full_id, prompt, route, task_id)
        finally:
            end_output_collection(token)
        self._consume_usage(_response_usage(response))
        outputs.update(_response_outputs(response))
        for name, spec in (node.get("outputs") or {}).items():
            hint = spec.get("path_hint")
            if name not in outputs and hint:
                workspace = self._workspace.get()
                path = (workspace / str(resolve_value(hint, {"inputs": inputs}))).resolve(
                    strict=False
                )
                if path.exists() and (path == workspace or workspace in path.parents):
                    outputs[name] = str(path.relative_to(workspace))
        result = {
            name: value for name, value in outputs.items() if name in (node.get("outputs") or {})
        }
        result["_magent_files_changed"] = _response_files_changed(response)
        result["_magent_summary"] = _response_summary(response)
        return result

    async def _run_decision(
        self,
        full_id: str,
        node: dict[str, Any],
        inputs: dict[str, Any],
        scope: dict[str, Any],
        route: Route | None,
        task_id: str,
    ) -> dict[str, Any]:
        block = node.get("decision") or {}
        branches = block.get("branches") or []
        selected = ""
        if block.get("evaluator", "agent") == "expression":
            for branch in branches:
                if bool(evaluate_expression(str(branch.get("when", "false")), scope)):
                    selected = str(branch["label"])
                    break
        else:
            labels = [str(branch["label"]) for branch in branches]
            if route is None:
                raise GraphRunError("decision node has no route", "RT011")
            response = await self.agent_runner(
                full_id, _decision_prompt(node, inputs, labels), route, task_id
            )
            parsed = response if isinstance(response, dict) else (_json_object(str(response)) or {})
            # An empty model response used to raise IndexError on splitlines()[0]
            # instead of falling through to default_branch.
            raw_lines = str(response).strip().strip('"').splitlines()
            selected = (
                str(parsed.get("decision", "")) if parsed else (raw_lines[0] if raw_lines else "")
            )
            declared = set(node.get("outputs") or {})
            response_outputs = parsed.get("outputs", {}) if isinstance(parsed, dict) else {}
            if isinstance(response_outputs, dict):
                outputs = {
                    name: value for name, value in response_outputs.items() if name in declared
                }
            else:
                outputs = {}
            outputs.update(
                {
                    name: parsed[name]
                    for name in declared
                    if isinstance(parsed, dict) and name in parsed
                }
            )
        if selected not in {str(branch["label"]) for branch in branches}:
            selected = str(block.get("default_branch", ""))
        if not selected:
            raise GraphRunError(
                "decision returned an undeclared branch and has no default", "RT022"
            )
        return {
            "decision": selected,
            **(outputs if block.get("evaluator", "agent") != "expression" else {}),
        }

    async def _run_gate(
        self, node_id: str, node: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]:
        gate = node.get("gate") or {}
        prompt = str(
            resolve_value(gate.get("prompt", node.get("description", "Approve this gate?")), scope)
        )
        approved = self.assume_yes
        if not approved and self.approval:
            call = self.approval(prompt, {**gate, "node_id": node_id})
            timeout = float(gate.get("timeout_seconds", 0) or 0)
            try:
                approved = await asyncio.wait_for(call, timeout) if timeout else await call
            except TimeoutError:
                timeout_action = gate.get("on_timeout", "fail")
                if timeout_action == "approve":
                    approved = True
                elif timeout_action == "hold":
                    return {"decision": "timed_out", "_status": "awaiting_human"}
                else:
                    raise GraphRunError("gate timed out", "RT015") from None
        if not approved and self.approval is None and not self.assume_yes:
            raise GraphRunError("human checkpoint cannot be presented", "RT015")
        if not approved:
            action = gate.get("on_reject", "fail")
            if action == "skip":
                return {"decision": "rejected", "_status": "skipped"}
            raise GraphRunError("gate rejected", "RT016")
        outputs = {"decision": "approved"}
        for name, expression in (gate.get("collect") or {}).items():
            outputs[name] = evaluate_expression(str(expression), scope)
        return outputs

    async def _run_loop(
        self, full_id: str, node: dict[str, Any], inputs: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]:
        block = node.get("loop") or {}
        body = block.get("body") or {}
        maximum = int(block.get("max_iterations", 1) or 1)
        local_params = _fragment_params(body, inputs)
        completed = 0
        child_scope: dict[str, Any] = {}
        for iteration in range(1, maximum + 1):
            loop_scope = {
                **scope,
                **local_params,
                "loop": {"iteration": iteration},
                "params": local_params,
            }
            mode = block.get("mode", "repeat")
            if mode == "while" and not bool(
                evaluate_expression(str(block.get("condition", "false")), loop_scope)
            ):
                break
            _statuses, _outputs = await self._run_nested_scope(
                body, loop_scope, scope_path=f"{full_id}[{iteration}]"
            )
            child_scope = loop_scope
            completed = iteration
            for name, expression in (block.get("carry") or {}).items():
                local_params[name] = evaluate_expression(str(expression), loop_scope)
            if mode == "until" and bool(
                evaluate_expression(str(block.get("condition", "false")), loop_scope)
            ):
                break
        else:
            if block.get("mode") != "repeat":
                action = block.get("on_max_iterations", "fail")
                # Only "escalate" is a question for a human. `fail` and
                # `succeed_partial` are already decisions, but the prompt fired
                # for all three.
                if action == "succeed_partial":
                    pass
                elif action == "escalate":
                    approval = self.approval
                    accepted = self.assume_yes or (
                        approval is not None
                        and bool(
                            await approval(
                                "Loop reached max_iterations. Accept the partial result?", block
                            )
                        )
                    )
                    if not accepted:
                        raise GraphRunError("loop reached max_iterations", "RT031")
                else:
                    raise GraphRunError("loop reached max_iterations", "RT031")
        outputs = {
            name: evaluate_expression(str(expression), child_scope or scope)
            for name, expression in (block.get("collect") or {}).items()
        }
        outputs["iterations"] = completed
        return outputs

    async def _run_map(
        self, full_id: str, node: dict[str, Any], inputs: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]:
        block = node.get("map") or {}
        values = evaluate_expression(str(block.get("over", "[]")), {**scope, "inputs": inputs})
        if not isinstance(values, list):
            raise GraphRunError("map.over must evaluate to an array", "RT032")
        maximum = int(block.get("max_items", len(values) or 1) or 1)
        if len(values) > maximum:
            raise GraphRunError(f"map has {len(values)} items, above max_items {maximum}", "RT032")
        semaphore = asyncio.Semaphore(
            max(
                1,
                min(
                    int(block.get("max_parallel", 1) or 1),
                    int(getattr(self.config, "max_parallel_subagents", 1)),
                ),
            )
        )

        async def run_item(index: int, value: Any) -> dict[str, Any]:
            async with semaphore:
                item_name = str(block.get("as", "item"))
                index_name = str(block.get("index_as", "index"))
                item_scope = {**scope, item_name: value, index_name: index, "params": inputs}
                statuses, _outputs = await self._run_nested_scope(
                    block.get("body") or {}, item_scope, scope_path=f"{full_id}[{index}]"
                )
                if (
                    any(status == "failed" for status in statuses.values())
                    and block.get("on_item_failure", "fail") == "fail"
                ):
                    raise GraphRunError(f"map item {index} failed", "RT033")
                return item_scope

        # TaskGroup, not gather: on the first failure gather leaves sibling
        # agent sessions and subprocesses running detached.
        item_results: list[Any] = [None] * len(values)

        async with asyncio.TaskGroup() as group:
            for index, value in enumerate(values):

                async def collect(index: int = index, value: Any = value) -> None:
                    item_results[index] = await run_item(index, value)

                group.create_task(collect())

        item_scopes = item_results
        outputs: dict[str, Any] = {}
        for name, expression in (block.get("collect") or {}).items():
            outputs[name] = [
                evaluate_expression(str(expression), item_scope) for item_scope in item_scopes
            ]
        outputs["items"] = len(values)
        return outputs

    async def _run_subgraph(
        self, full_id: str, node: dict[str, Any], inputs: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]:
        block = node.get("subgraph") or {}
        fragment: dict[str, Any]
        if block.get("use"):
            fragment = (
                (self._document.data.get("subgraphs") or {}).get(block["use"])
                if self._document
                else None
            ) or {}
        elif block.get("inline"):
            fragment = block["inline"]
        elif block.get("ref"):
            ref = block["ref"]
            uri = str(ref.get("uri", ""))
            if "://" in uri:
                raise GraphRunError("remote subgraph references are not supported", "RT040")
            base = (
                self._document.path.parent
                if self._document and self._document.path
                else self.project
            )
            ref_path = (base / uri).resolve()
            if ref_path != base.resolve() and base.resolve() not in ref_path.parents:
                raise GraphRunError("subgraph reference escapes its document directory", "RT040")
            child = load_graph(ref_path)
            if ref.get("integrity") and child.digest != ref["integrity"]:
                raise GraphRunError("subgraph integrity mismatch", "RT041")
            if ref.get("expected_id") and child.graph_id != ref["expected_id"]:
                raise GraphRunError("subgraph id mismatch", "RT042")
            fragment = child.data
        else:
            raise GraphRunError("subgraph has no source", "RT040")
        param_scope = {**scope, "inputs": inputs}
        child_params = {
            name: _agx_or_literal(value, param_scope)
            for name, value in (block.get("params") or {}).items()
        }
        child_scope = {**scope, "params": child_params or inputs}
        statuses, _outputs = await self._run_nested_scope(fragment, child_scope, scope_path=full_id)
        if any(status == "failed" for status in statuses.values()):
            raise GraphRunError("subgraph failed", "RT043")
        child_scope["outputs"] = self._resolve_graph_outputs(fragment, child_scope)
        mapping = block.get("outputs_from") or fragment.get("outputs") or {}
        # `outputs_from` values may be literals as well as references, so they
        # go through template resolution like every other input path rather
        # than being parsed as raw AGX.
        return {
            name: _agx_or_literal(spec.get("from") if isinstance(spec, dict) else spec, child_scope)
            for name, spec in mapping.items()
        }

    async def _fallback(
        self, node_id: str, node: dict[str, Any], outputs: dict[str, Any], scope: dict[str, Any]
    ) -> str:
        failure = node.get("failure") or {}
        for fallback in failure.get("fallback") or []:
            if fallback.get("when") and not bool(evaluate_expression(str(fallback["when"]), scope)):
                continue
            strategy = fallback.get("strategy")
            if strategy == "skip":
                return "skipped"
            if strategy == "degrade_outputs" and all(
                name in outputs for name in fallback.get("outputs") or []
            ):
                return "succeeded"
            if strategy == "relax_criteria":
                relaxed = []
                selected = set(fallback.get("criteria") or [])
                for criterion in (node.get("success") or {}).get("criteria") or []:
                    relaxed.append(
                        {
                            **criterion,
                            "severity": "advisory"
                            if criterion.get("id") in selected
                            else criterion.get("severity", "required"),
                        }
                    )
                success = node.get("success") or {}
                passed, _results = await self._criteria(
                    relaxed,
                    outputs,
                    scope,
                    mode=str(success.get("mode", "all")),
                    count=int(success.get("count", 1) or 1),
                )
                if passed:
                    return "succeeded"
            if strategy == "human_takeover":
                if self.approval and await self.approval(
                    fallback.get("description", f"Take over node {node_id}?"), fallback
                ):
                    return "succeeded"
                return "awaiting_human"
            if strategy == "alternate_node":
                alternate_id = str(fallback.get("node") or "")
                if alternate_id in self._fallback_chain:
                    self._diagnostic(
                        "RT001",
                        "error",
                        f"alternate_node cycle: {' -> '.join([*self._fallback_chain, alternate_id])}",
                        node_id=node_id,
                    )
                    continue
                alternate = (
                    (self._document.data.get("nodes") or {}).get(alternate_id)
                    if self._document
                    else None
                )
                if alternate:
                    self._fallback_chain.append(alternate_id)
                    try:
                        status, replacement = await self._execute_node(
                            alternate_id, alternate, scope, "fallback"
                        )
                    finally:
                        self._fallback_chain.pop()
                    outputs.update(replacement)
                    if status == "succeeded":
                        return "succeeded"
        exhausted = failure.get("on_exhausted", "fail")
        if exhausted == "skip":
            return "skipped"
        if exhausted == "succeed_degraded":
            return "succeeded"
        if exhausted == "escalate" and self.approval:
            return (
                "succeeded"
                if await self.approval(
                    f"Accept failed node {node_id}?", failure.get("escalation") or {}
                )
                else "failed"
            )
        return "failed"

    async def _criteria(
        self,
        criteria: list[dict[str, Any]],
        outputs: dict[str, Any],
        scope: dict[str, Any],
        *,
        mode: str = "all",
        count: int = 1,
    ) -> tuple[bool, list[CriterionResult]]:
        return await evaluate_criteria(
            criteria,
            outputs=outputs,
            scope=scope,
            project=self._workspace.get(),
            command_runner=self._run_command_criterion,
            approval=self.approval,
            judge=self._judge,
            mode=mode,
            count=count,
        )

    async def _run_command_criterion(self, command: str, timeout: int, cwd: str) -> dict[str, Any]:
        from magent.tools.executor import ToolExecutor

        workspace = self._workspace.get()
        root = (workspace / cwd).resolve(strict=False) if cwd else workspace
        if root != workspace and workspace not in root.parents:
            return {"ok": False, "returncode": -1, "stderr": "criterion cwd escapes workspace"}
        executor = ToolExecutor(
            str(root),
            permission_mode=str(getattr(self.config, "permission_mode", "balanced")),
            username=self.username,
            config=self.config,
            interactive_permissions=not self.assume_yes,
        )
        result = await executor.dispatch("run_shell", {"command": command, "timeout": timeout})
        return {**result, "returncode": result.get("returncode", 0 if result.get("ok") else -1)}

    async def _judge(
        self, rubric: str, inputs: list[Any], criterion: dict[str, Any]
    ) -> tuple[float, str]:
        node = {"intelligence": criterion.get("judge_intelligence") or {"tier": "advanced"}}
        route = route_for_node(self.config, node)
        prompt = f'Judge the material against this rubric. Return JSON {{"score": 0.0, "reason": "..."}}.\nRubric: {rubric}\nMaterial: {json.dumps(inputs, default=str)}'
        response = await self.agent_runner("judge", prompt, route, self._root_task_id)
        parsed = _json_object(str(response)) or {}
        return float(parsed.get("score", 0)), str(parsed.get("reason", response))

    async def _default_agent_runner(
        self, node_id: str, prompt: str, route: Route, task_id: str
    ) -> Any:
        from magent.agent import AgentSession
        from magent.cli.command_context import (
            build_extraction_provider,
            build_provider,
            build_provider_for_role,
        )

        profile = self._active_profile.get()
        provider = (
            build_provider(self.config, profile.provider, profile.model)
            if profile and (profile.provider or profile.model)
            else build_provider_for_role(self.config, route.role)
        )
        extraction = build_extraction_provider(self.config)
        session = AgentSession(
            username=self.username,
            config=self.config,
            provider=provider,
            extraction_provider=extraction,
            cwd=str(self._workspace.get()),
            project_slug=None,
            profile=profile,
        )
        session.execution_task_id = task_id
        try:
            response = await session.chat(prompt)
            from magent.session_controls import session_usage

            return {
                "outputs": _response_outputs(response),
                "response": response,
                "_usage": session_usage(session.logger._path),
            }
        finally:
            with contextlib.suppress(Exception):
                await session.end_session()

    def _profile_for_node(self, node: dict[str, Any]) -> Any | None:
        name = str(node.get("x-magagent-profile") or "").strip().lstrip("@").lower()
        if not name:
            return self.profile
        if name in self._profile_cache:
            return self._profile_cache[name]
        from magent.agent_profiles.effective import resolve_effective_profile
        from magent.agent_profiles.registry import AgentProfileRegistry
        from magent.tools.catalog import built_in_tool_definitions

        resolved = AgentProfileRegistry(self.project, self.config).get(name)
        if resolved is None:
            raise GraphRunError(f"Agent profile not found: {name}", "RT012")
        granted = {
            str(item.get("function", {}).get("name", "")) for item in built_in_tool_definitions()
        }
        profile = resolve_effective_profile(resolved, self.config, granted)
        self._profile_cache[name] = profile
        return profile

    def _resolve_inputs(self, node: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for name, spec in (node.get("inputs") or {}).items():
            if "from" in spec:
                result[name] = resolve_reference(scope, str(spec["from"]))
            elif "template" in spec:
                result[name] = resolve_value(spec["template"], scope)
            elif "value" in spec:
                result[name] = resolve_value(spec["value"], scope)
            elif "default" in spec:
                result[name] = spec["default"]
        return result

    def _resolve_graph_outputs(
        self, document: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]:
        outputs = {}
        for name, spec in (document.get("outputs") or {}).items():
            expression = spec.get("from") if isinstance(spec, dict) else spec
            try:
                try:
                    outputs[name] = resolve_reference(scope, str(expression))
                except AgxEvaluationError:
                    outputs[name] = evaluate_expression(str(expression), scope)
            except AgxEvaluationError as exc:
                if isinstance(spec, dict) and not spec.get("required", True):
                    continue
                raise GraphRunError(
                    f"required graph output {name!r} is unavailable: {exc}", "RT024"
                ) from exc
        return outputs

    def _base_scope(self, document: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        attachments = {item["name"]: item for item in document.get("attachments") or []}
        graph_metadata = {
            key: document.get(key, "")
            for key in ("id", "title", "objective", "version", "description")
        }
        return {
            "params": params,
            "context": document.get("context") or {},
            "attachments": attachments,
            "nodes": {},
            "graph": graph_metadata,
        }

    def _preflight(self, document: GraphDocument, plan: Any) -> None:
        constraints = document.data.get("constraints") or {}
        if constraints.get("max_node_executions") and plan.worst_case_node_executions > int(
            constraints["max_node_executions"]
        ):
            raise GraphRunError("worst-case node executions exceed graph budget", "RT012")
        # Cost estimates are advisory and may include mutually exclusive branches.
        # Actual usage is enforced before and after each node execution.

    def _enforce_requirements(self, node: dict[str, Any]) -> None:
        from magent.skills import SkillRegistry
        from magent.tools.catalog import built_in_tool_definitions

        available = {item["function"]["name"] for item in built_in_tool_definitions()}
        requirements = node.get("requirements") or {}
        for item in requirements.get("tools") or []:
            name, optional, _alternatives = tool_requirement(item)
            if not optional and not any(tool in available for tool in tools_for_requirement(item)):
                raise GraphRunError(f"required tool {name!r} is unavailable", "RT012")
        registry = SkillRegistry()
        registry.load(respect_lockfile=False)
        available_skills = {skill.name for skill in registry.skills}
        missing_skills = sorted(set(requirements.get("skills") or []) - available_skills)
        if missing_skills:
            raise GraphRunError(
                f"required skills are unavailable: {', '.join(missing_skills)}", "RT012"
            )
        declared_secrets = _declared_secret_names(self._document.data if self._document else {})
        for secret in requirements.get("secrets") or []:
            if secret not in declared_secrets:
                raise GraphRunError(f"secret {secret!r} is not declared by the graph", "RT012")
            if not _secret_value(str(secret)):
                raise GraphRunError(f"required secret {secret!r} is unavailable", "RT012")

    def _tool_policy(
        self, node: dict[str, Any], scope: dict[str, Any], full_id: str = ""
    ) -> GraphToolPolicy:
        requirements = node.get("requirements") or {}
        allowed = {
            tool for item in requirements.get("tools") or [] for tool in tools_for_requirement(item)
        }
        checkpoints = [
            item for item in node.get("human") or [] if item.get("at") == "before_side_effects"
        ]
        checkpoint = checkpoints[0] if checkpoints else {}

        async def approve(prompt: str, detail: dict[str, Any]) -> bool:
            if self.assume_yes:
                return True
            if self.approval is None:
                raise GraphRunError("human checkpoint cannot be presented", "RT015")
            return await self.approval(prompt, detail)

        node_tool_calls = 0
        node_tool_limit = int((node.get("constraints") or {}).get("max_tool_calls", 0) or 0)

        def observe(_tool: str, _args: dict[str, Any]) -> str | None:
            nonlocal node_tool_calls
            node_tool_calls += 1
            self._record["usage"]["tool_calls"] += 1
            if full_id:
                self._emit_node(
                    "node.tool.requested",
                    full_id,
                    node,
                    "running",
                    tool=_tool,
                    summary=f"Requested declared tool {_tool}.",
                )
            if node_tool_limit and node_tool_calls > node_tool_limit:
                return "RT030 node tool-call budget exceeded"
            return None

        return GraphToolPolicy(
            allowed_tools=allowed,
            permissions=tuple(str(item) for item in requirements.get("permissions") or []),
            approval=approve if checkpoint else None,
            approval_prompt=str(
                resolve_value(
                    checkpoint.get("prompt", "Approve side effects for this graph node?"), scope
                )
            ),
            observer=observe,
        )

    async def _checkpoint(
        self,
        node: dict[str, Any],
        stage: str,
        scope: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        for checkpoint in node.get("human") or []:
            if checkpoint.get("at") != stage:
                continue
            if checkpoint.get("when") and not bool(
                evaluate_expression(str(checkpoint["when"]), scope)
            ):
                continue
            mode = str(checkpoint.get("mode", "approve"))
            prompt = str(resolve_value(checkpoint.get("prompt", f"Continue after {stage}?"), scope))
            approved = self.assume_yes
            if mode == "notify":
                approved = True
            elif not approved:
                if self.approval is None:
                    if checkpoint.get("required", True):
                        raise GraphRunError("human checkpoint cannot be presented", "RT015")
                    continue
                timeout = float(checkpoint.get("timeout_seconds", 0) or 0)
                call = self.approval(prompt, checkpoint)
                try:
                    approved = await asyncio.wait_for(call, timeout) if timeout else await call
                except TimeoutError as exc:
                    if checkpoint.get("on_timeout") == "approve":
                        approved = True
                    else:
                        raise GraphRunError("human checkpoint timed out", "RT015") from exc
            events.append(
                {
                    "checkpoint_id": str(checkpoint.get("id", "")),
                    "at_stage": stage,
                    "mode": mode,
                    "outcome": "notified"
                    if mode == "notify"
                    else ("approved" if approved else "rejected"),
                    "actor": "user" if mode != "notify" else "harness",
                    "at": now_iso(),
                }
            )
            events[-1] = {key: value for key, value in events[-1].items() if value != ""}
            if not approved and checkpoint.get("required", True):
                raise GraphRunError("human checkpoint rejected", "RT015")

    def _enforce_node_constraints(self, node: dict[str, Any]) -> None:
        constraints = node.get("constraints") or {}
        isolation = constraints.get("isolation", "shared")
        supported = {"shared", "worktree", "sandbox", "container"}
        if isolation not in supported:
            raise GraphRunError(f"unsupported isolation {isolation!r}", "RT014")
        if constraints.get("determinism") == "strict" and (
            constraints.get("temperature", 0) != 0 or "seed" not in constraints
        ):
            raise GraphRunError("strict determinism requires temperature 0 and a seed", "RT013")

    def _check_global_budget(self, document: dict[str, Any]) -> None:
        constraints = document.get("constraints") or {}
        elapsed = time.monotonic() - self._started
        if constraints.get("max_wall_clock_seconds") and elapsed > float(
            constraints["max_wall_clock_seconds"]
        ):
            raise GraphRunError("graph wall-clock budget exceeded", "RT030")
        if constraints.get("max_node_executions") and self._record["usage"][
            "node_executions"
        ] >= int(constraints["max_node_executions"]):
            raise GraphRunError("graph node-execution budget exceeded", "RT030")
        if constraints.get("max_total_tokens") and self._record["usage"].get(
            "total_tokens", 0
        ) >= int(constraints["max_total_tokens"]):
            raise GraphRunError("graph token budget exceeded", "RT030")
        if constraints.get("max_cost_usd") and self._record["usage"].get("cost_usd", 0) >= float(
            constraints["max_cost_usd"]
        ):
            raise GraphRunError("graph cost budget exceeded", "RT030")

    def _consume_usage(self, usage: dict[str, Any]) -> None:
        self._agent_steps.set(int(usage.get("turns", 0) or 0))
        # Accumulate against the *running node* as well as the graph. Diffing
        # the global counter charged each node for whatever its concurrently
        # running siblings spent, and killed nodes with RT030 for usage they
        # never incurred.
        node_usage = self._node_usage.get()
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            target = {"prompt_tokens": "input_tokens", "completion_tokens": "output_tokens"}.get(
                key, key
            )
            amount = int(usage.get(key, 0) or 0)
            self._record["usage"][target] = int(self._record["usage"].get(target, 0)) + amount
            if node_usage is not None:
                node_usage[target] = int(node_usage.get(target, 0)) + amount
        cost = float(usage.get("cost_usd", 0) or 0)
        self._record["usage"]["cost_usd"] = round(
            float(self._record["usage"].get("cost_usd", 0)) + cost, 8
        )
        if node_usage is not None:
            node_usage["cost_usd"] = round(float(node_usage.get("cost_usd", 0)) + cost, 8)

    def _enforce_usage_budgets(self, node: dict[str, Any], before: dict[str, Any]) -> None:
        constraints = node.get("constraints") or {}
        # Per-node accumulation when available, so siblings cannot bill us.
        node_usage = self._node_usage.get()
        delta = (
            dict(node_usage)
            if node_usage is not None
            else _usage_delta(before, self._record["usage"])
        )
        checks = (
            ("max_input_tokens", "input_tokens", "input-token"),
            ("max_output_tokens", "output_tokens", "output-token"),
            ("max_total_tokens", "total_tokens", "token"),
            ("max_cost_usd", "cost_usd", "cost"),
        )
        for limit_key, usage_key, label in checks:
            limit = constraints.get(limit_key)
            if limit and float(delta.get(usage_key, 0)) > float(limit):
                raise GraphRunError(f"node {label} budget exceeded", "RT030")
        if constraints.get("max_agent_steps") and self._agent_steps.get() > int(
            constraints["max_agent_steps"]
        ):
            raise GraphRunError("node agent-step budget exceeded", "RT030")
        graph_constraints = (self._document.data.get("constraints") if self._document else {}) or {}
        if graph_constraints.get("max_total_tokens") and int(
            self._record["usage"].get("total_tokens", 0)
        ) > int(graph_constraints["max_total_tokens"]):
            raise GraphRunError("graph token budget exceeded", "RT030")
        if graph_constraints.get("max_cost_usd") and float(
            self._record["usage"].get("cost_usd", 0)
        ) > float(graph_constraints["max_cost_usd"]):
            raise GraphRunError("graph cost budget exceeded", "RT030")

    async def _compensate(self, scope: dict[str, Any]) -> None:
        if not self._document:
            return
        nodes = self._document.data.get("nodes") or {}
        for _node_id, node in reversed(self._completed_for_compensation):
            compensation = (node.get("failure") or {}).get("compensation")
            target = nodes.get(compensation) if compensation else None
            if target:
                with contextlib.suppress(Exception):
                    await self._execute_node(str(compensation), target, scope, "compensation")

    def _ensure_node_task(
        self,
        full_id: str,
        node: dict[str, Any],
        *,
        state: TaskState = "ready",
        summary: str = "",
        blocked_by: list[dict[str, str]] | None = None,
    ) -> str:
        existing = self._node_tasks.get(full_id)
        if existing:
            return existing
        node_id = full_id.split(".")[-1].split("[")[0]
        profile_name = str(
            node.get("x-magagent-profile") or getattr(self.profile, "name", "") or ""
        )
        task = self.runtime.create(
            "agentic_graph_node",
            node.get("title", node_id),
            project=self.project,
            parent_task_id=self._root_task_id,
            permission_policy=str(getattr(self.config, "permission_mode", "balanced")),
            state=state,
            metadata={
                "node_id": node_id,
                "scope_path": full_id,
                "graph_node_id": full_id,
                "run_id": self._record["run_id"],
                "graph_id": self._record["graph_id"],
                "graph_digest": self._record["graph_digest"],
                "agent_profile": profile_name,
                "dependencies": list(node.get("depends_on") or []),
                "blocked_by": blocked_by or [],
                "summary": summary,
                "event_schema_version": GRAPH_EVENT_SCHEMA_VERSION,
            },
        )
        self._node_tasks[full_id] = task["id"]
        if summary:
            self.runtime.update_context(
                task["id"],
                final_audit={"ok": state == "succeeded", "summary": summary},
                metadata={"result_summary": summary},
            )
        self._emit_node(
            "node.queued" if state == "ready" else "node.completed",
            full_id,
            node,
            state,
            task_id=task["id"],
            summary=summary,
            blocked_by=blocked_by or [],
        )
        return task["id"]

    def _terminalize_nonexecuted(
        self,
        full_id: str,
        node: dict[str, Any],
        state: TaskState,
        summary: str,
        error_code: str,
        *,
        blocked_by: list[dict[str, str]] | None = None,
    ) -> None:
        task_id = self._ensure_node_task(full_id, node)
        task = self.runtime.get(task_id)
        if task and task["state"] != state:
            if state == "failed" and task["state"] == "ready":
                self.runtime.transition(
                    task_id, "blocked", reason=summary, detail={"error_code": error_code}
                )
            self.runtime.transition(
                task_id,
                state,
                reason=summary,
                detail={"error_code": error_code, "blocked_by": blocked_by or []},
            )
        self.runtime.update_context(
            task_id,
            final_audit={"ok": False, "summary": summary, "error_code": error_code},
            metadata={
                "summary": summary,
                "result_summary": summary,
                "blocked_by": blocked_by or [],
            },
        )
        self._append_node_record(
            full_id,
            node,
            state,
            {},
            [],
            summary=summary,
            error_code=error_code,
            blocked_by=blocked_by or [],
        )
        self._emit_node(
            "node.completed",
            full_id,
            node,
            state,
            task_id=task_id,
            summary=summary,
            error_code=error_code,
            blocked_by=blocked_by or [],
        )

    def _emit(self, event_type: str, *, state: str, **detail: Any) -> dict[str, Any]:
        event = graph_event(
            event_type,
            run_id=str(self._record.get("run_id", "")),
            graph_id=str(self._record.get("graph_id", "")),
            graph_digest=str(self._record.get("graph_digest", "")),
            task_id=self._root_task_id,
            state=state,
            **detail,
        )
        if self._root_task_id:
            with contextlib.suppress(Exception):
                self.runtime.record_event(self._root_task_id, "graph_lifecycle", detail=event)
        if self.event_sink:
            self.event_sink(event)
        return event

    def _emit_node(
        self, event_type: str, full_id: str, node: dict[str, Any], state: str, **detail: Any
    ) -> dict[str, Any]:
        node_id = full_id.split(".")[-1].split("[")[0]
        node_task_id = str(detail.pop("task_id", "") or "")
        event = graph_event(
            event_type,
            run_id=str(self._record.get("run_id", "")),
            graph_id=str(self._record.get("graph_id", "")),
            graph_digest=str(self._record.get("graph_digest", "")),
            task_id=self._root_task_id,
            state=state,
            node_id=node_id,
            scope_path=full_id,
            title=str(node.get("title") or node_id),
            profile=str(node.get("x-magagent-profile") or getattr(self.profile, "name", "") or ""),
            dependencies=[str(item) for item in node.get("depends_on") or []],
            node_task_id=node_task_id,
            **detail,
        )
        # Child task state is already durable. Live consumers receive the full
        # versioned event, while reconnect snapshots synthesize it from that
        # ledger rather than duplicating every transition in SQLite.
        if self.event_sink:
            self.event_sink(event)
        return event

    def _finalize_root_task(self, failed: bool, *, error: str = "", error_code: str = "") -> None:
        summary = _run_summary(self._record)
        self._record.setdefault("metadata", {})["x-magagent-summary"] = summary
        with contextlib.suppress(Exception):
            self.runtime.update_context(
                self._root_task_id,
                usage=self._record.get("usage") or {},
                final_audit={
                    "ok": not failed,
                    "summary": summary["text"],
                    "error": error,
                    "error_code": error_code,
                    **summary,
                },
                metadata={
                    "summary": summary["text"],
                    "result_summary": summary["text"],
                    "run_status": self._record.get("status"),
                },
            )

    def _append_node_record(
        self,
        full_id: str,
        node: dict[str, Any],
        status: str,
        inputs: dict[str, Any],
        attempts: list[dict[str, Any]],
        outputs: dict[str, Any] | None = None,
        human_events: list[dict[str, Any]] | None = None,
        *,
        summary: str = "",
        files_changed: list[str] | None = None,
        error_code: str = "",
        blocked_by: list[dict[str, str]] | None = None,
    ) -> None:
        record = {
            "node_id": full_id.split(".")[-1].split("[")[0],
            "scope_path": full_id,
            "type": node.get("type", "task"),
            "status": status
            if status
            in {
                "pending",
                "ready",
                "running",
                "awaiting_human",
                "succeeded",
                "failed",
                "skipped",
                "cancelled",
                "blocked",
            }
            else "failed",
            "started_at": attempts[0]["started_at"] if attempts else now_iso(),
            "finished_at": now_iso(),
            "inputs": _redact_values(node.get("inputs") or {}, inputs),
            "outputs": _redact_values(node.get("outputs") or {}, outputs or {}),
            "attempts": attempts,
            "usage": _sum_usage(attempts),
            "x-magagent-dependencies": list(node.get("depends_on") or []),
            "x-magagent-summary": summary
            or _node_summary(node, status, outputs or {}, attempts, ""),
            "x-magagent-files-changed": files_changed or [],
        }
        if error_code:
            record["x-magagent-error-code"] = error_code
        if blocked_by:
            record["x-magagent-blocked-by"] = blocked_by
        if attempts and attempts[-1].get("error"):
            record["x-magagent-error"] = str(attempts[-1]["error"])
        if node.get("x-magagent-profile"):
            record["x-magagent-profile"] = str(node["x-magagent-profile"])
        if human_events:
            record["human_events"] = human_events
        if node.get("type") == "decision" and outputs:
            record["decision"] = outputs.get("decision", "")
        if node.get("type") == "loop" and outputs:
            record["iterations"] = int(outputs.get("iterations", 0))
        if node.get("type") == "map" and outputs:
            record["items"] = int(outputs.get("items", 0))
        self._record["nodes"].append(record)
        self._node_records[full_id] = record

    def _diagnostic(self, code: str, severity: str, message: str, *, node_id: str = "") -> None:
        item = {"code": code, "severity": severity, "message": message, "at": now_iso()}
        if node_id:
            item["node_id"] = node_id
        self._record.setdefault("diagnostics", []).append(item)

    def _finish(self, status: str) -> None:
        self._record["status"] = status
        self._record["finished_at"] = now_iso()
        self._record["usage"]["wall_clock_seconds"] = round(time.monotonic() - self._started, 6)

    def _persist_record(self) -> None:
        self._record = _redact_secrets(self._record, self._document.data if self._document else {})
        records = self.store.read("graph_runs", [])
        for item in records:
            if item.get("run_id") == self._record.get("run_id"):
                item.update(self._record)
                break
        else:
            records.append(self._record)
        self.store.write("graph_runs", records)


def _bind_params(document: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for name, spec in (document.get("params") or {}).items():
        if name in supplied:
            value = supplied[name]
        elif "default" in spec:
            value = spec["default"]
        elif spec.get("required", True):
            raise GraphRunError(f"missing required parameter {name!r}", "AG301")
        else:
            continue
        if spec.get("enum") and value not in spec["enum"]:
            raise GraphRunError(f"parameter {name!r} is outside its enum", "AG302")
        result[name] = value
    unknown = set(supplied) - set(document.get("params") or {})
    if unknown:
        raise GraphRunError(f"unknown parameters: {', '.join(sorted(unknown))}", "AG302")
    return result


def _agx_or_literal(value: Any, scope: dict[str, Any]) -> Any:
    """Evaluate a subgraph param/output binding.

    These fields carry bare AGX expressions (`params.label`, `outputs.result`),
    unlike every other input path, which is template-only. Running AGX on every
    string meant a plain literal — `"hello world"`, a path, a sentence — was a
    parse error rather than a value. References still evaluate; anything AGX
    cannot parse is taken literally.
    """
    if not isinstance(value, str):
        return resolve_value(value, scope)
    try:
        return evaluate_expression(value, scope)
    except AgxEvaluationError:
        return resolve_value(value, scope)


def _fragment_params(fragment: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    result = {
        name: spec["default"]
        for name, spec in (fragment.get("params") or {}).items()
        if isinstance(spec, dict) and "default" in spec
    }
    result.update(supplied)
    return result


def _failure_class(status: str, error: str) -> str:
    if status in {"timeout", "budget_exceeded", "criteria_failed"}:
        return status
    lowered = error.lower()
    if "missing required output" in lowered:
        return "output_missing"
    if "permission" in lowered or "rt012" in lowered:
        return "permission_denied"
    if "provider" in lowered or "model" in lowered:
        return "model_error"
    return "tool_error"


def _retry_delay(retry: dict[str, Any], attempt: int) -> float:
    mode = str(retry.get("backoff", "exponential"))
    initial = float(retry.get("initial_delay_seconds", 2) or 0)
    maximum = float(retry.get("max_delay_seconds", 60) or 60)
    if mode == "none":
        return 0
    multiplier = 1 if mode == "fixed" else attempt if mode == "linear" else 2 ** (attempt - 1)
    return min(maximum, initial * multiplier)


def _redact_values(specs: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    return {
        name: "[REDACTED]" if (specs.get(name) or {}).get("redact") else value
        for name, value in values.items()
    }


def _contains_redaction(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_redaction(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_redaction(item) for item in value)
    return value == "[REDACTED]"


def _secret_value(name: str) -> str:
    return (
        os.environ.get(name)
        or os.environ.get(name.upper())
        or os.environ.get(f"MAGENT_SECRET_{name.upper()}", "")
    )


def _redact_secrets(value: Any, document: dict[str, Any]) -> Any:
    secrets = [
        secret for name in _declared_secret_names(document) if (secret := _secret_value(name))
    ]
    if isinstance(value, dict):
        return {key: _redact_secrets(item, document) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_secrets(item, document) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, "[REDACTED]")
        return result
    return value


def _declared_secret_names(document: dict[str, Any]) -> set[str]:
    return {
        str(item.get("name", "")) if isinstance(item, dict) else str(item)
        for item in document.get("secrets") or []
        if (item.get("name") if isinstance(item, dict) else item)
    }


def _node_prompt(node: dict[str, Any], inputs: dict[str, Any], feedback: str) -> str:
    outputs = node.get("outputs") or {}
    contract = {
        name: {"type": spec.get("type", "json"), "description": spec.get("description", "")}
        for name, spec in outputs.items()
    }
    parts = [
        "You are executing one bounded Agentic Graph node.",
        f"Task: {node.get('title', '')}\n{node.get('description', '')}",
        f"Resolved inputs (immutable for this attempt):\n{json.dumps(inputs, indent=2, default=str)}",
        f"Declared outputs:\n{json.dumps(contract, indent=2)}",
        "Complete the task using only the needed tools. For every declared output, call graph_emit_output(name, value). Do not merely describe an artifact that should exist.",
    ]
    if feedback:
        parts.append(f"Previous attempt failed. Correct these exact issues:\n{feedback}")
    return "\n\n".join(parts)


def _decision_prompt(node: dict[str, Any], inputs: dict[str, Any], labels: list[str]) -> str:
    outputs = {
        name: {"type": spec.get("type", "json"), "description": spec.get("description", "")}
        for name, spec in (node.get("outputs") or {}).items()
    }
    return (
        "Choose exactly one declared decision label. Return JSON as "
        '{"decision": "<label>", "outputs": {"<declared-name>": "<value>"}}. '
        "Include every declared output.\n"
        f"Task: {node.get('description', '')}\n"
        f"Inputs: {json.dumps(inputs, default=str)}\n"
        f"Labels: {json.dumps(labels)}\n"
        f"Declared outputs: {json.dumps(outputs)}"
    )


def _response_outputs(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        value = response.get("outputs", response)
        return value if isinstance(value, dict) else {}
    parsed = _json_object(str(response))
    if not parsed:
        return {}
    value = parsed.get("outputs", parsed)
    return value if isinstance(value, dict) else {}


def _response_usage(response: Any) -> dict[str, Any]:
    if isinstance(response, dict) and isinstance(response.get("_usage"), dict):
        return response["_usage"]
    return {}


def _response_files_changed(response: Any) -> list[str]:
    if not isinstance(response, dict):
        return []
    value = response.get("files_changed") or response.get("files") or []
    return [str(item) for item in value] if isinstance(value, list) else []


def _response_summary(response: Any) -> str:
    if isinstance(response, dict):
        for key in ("summary", "result_summary", "response"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:2000]
    return ""


def _error_code(error: str) -> str:
    match = re.search(r"\b((?:RT|AG)\d{3}|GRAPH_[A-Z0-9_]+)\b", error)
    return match.group(1) if match else ("GRAPH_NODE_FAILED" if error else "")


def _node_summary(
    node: dict[str, Any],
    status: str,
    outputs: dict[str, Any],
    attempts: list[dict[str, Any]],
    response_summary: str,
) -> str:
    if response_summary:
        return response_summary
    for key in ("summary", "report", "result", "message"):
        value = outputs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:2000]
    title = str(node.get("title") or "Job")
    if status == "succeeded":
        return f"{title} completed successfully."
    if status == "skipped":
        return f"{title} was skipped because its execution route was not active."
    error = str(attempts[-1].get("error", "")) if attempts else ""
    return f"{title} failed: {error}" if error else f"{title} did not complete successfully."


def _run_summary(record: dict[str, Any]) -> dict[str, Any]:
    nodes = record.get("nodes") or []
    succeeded = [
        str(item.get("scope_path") or item.get("node_id"))
        for item in nodes
        if item.get("status") == "succeeded"
    ]
    failed = [
        str(item.get("scope_path") or item.get("node_id"))
        for item in nodes
        if item.get("status") in {"failed", "blocked", "cancelled"}
    ]
    skipped = [
        str(item.get("scope_path") or item.get("node_id"))
        for item in nodes
        if item.get("status") == "skipped"
    ]
    text = f"Graph {record.get('status')}: {len(succeeded)} succeeded, {len(failed)} failed or blocked, {len(skipped)} skipped."
    return {
        "text": text,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "total": len(nodes),
    }


def _retry_closure(document: dict[str, Any], selected: set[str]) -> set[str]:
    closure = set(selected)
    changed = True
    edges = effective_edges(document)
    while changed:
        changed = False
        for source, target, _kind, _when in edges:
            if source in closure and target not in closure:
                closure.add(target)
                changed = True
    return closure


def _usage_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
        "tool_calls",
        "wall_clock_seconds",
        "node_executions",
    )
    result = {}
    for key in keys:
        value = float(after.get(key, 0) or 0) - float(before.get(key, 0) or 0)
        if key in {"cost_usd", "wall_clock_seconds"}:
            result[key] = round(max(0.0, value), 8)
        else:
            result[key] = max(0, int(value))
    return result


def _sum_usage(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    total: dict[str, Any] = {"node_executions": len(attempts)}
    for attempt in attempts:
        for key, value in (attempt.get("usage") or {}).items():
            if key == "node_executions":
                continue
            total[key] = total.get(key, 0) + value
    return total


def _json_object(text: str) -> dict[str, Any] | None:
    candidates = [text.strip()]
    candidates.extend(
        match.group(1) for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    )
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return None


def _failed_feedback(results: list[CriterionResult], error: str) -> str:
    lines = [error] if error else []
    lines.extend(
        f"- {item.id}: {item.error or item.evidence or 'criterion failed'}"
        for item in results
        if not item.passed and item.severity == "required"
    )
    return "\n".join(lines)
