"""Graph catalogue and background execution support for the bundled Web UI."""

from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from magent.agraph.authoring import model_graph_draft, node_template, preview_graph, save_graph
from magent.agraph.document import load_graph
from magent.agraph.execute import GraphExecutor
from magent.agraph.plan import resolved_plan
from magent.agraph.status import graph_status
from magent.config import load_config
from magent.workbench_store import WorkbenchStore

GRAPH_SUFFIXES = (".agraph.yaml", ".agraph.yml", ".agraph.json")


def confined_graph_target(project: str | Path, raw_path: str) -> Path:
    """Resolve a new or existing graph target without allowing project escape."""
    root = Path(project).resolve()
    candidate = Path(raw_path).expanduser()
    candidate = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=False)
    if candidate == root or root not in candidate.parents:
        raise ValueError("graph path must stay inside the selected project")
    if not candidate.name.lower().endswith(GRAPH_SUFFIXES):
        raise ValueError("graph must use .agraph.yaml, .agraph.yml, or .agraph.json")
    return candidate


def blank_graph_document(goal: str = "") -> dict[str, Any]:
    """Return an editable graph shell; it becomes runnable after its first card."""
    objective = goal.strip()
    title = objective.rstrip(".")[:180] or "Untitled workflow"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "untitled"
    return {
        "ags_version": "1.0",
        "kind": "AgenticGraph",
        "id": f"magent/web/{slug}",
        "title": title,
        "objective": objective or "Describe the outcome this workflow should achieve.",
        "version": "1.0.0",
        "requires_conformance": 1,
        "constraints": {"max_parallel_nodes": 1, "max_node_executions": 50},
        "policy": {
            "on_expression_error": "fail",
            "on_node_failure": "halt",
            "checkpointing": "per_node",
        },
        "entrypoints": [],
        "nodes": {},
        "outputs": {},
    }


def web_task_node(index: int = 1) -> dict[str, Any]:
    """Return a strictly-valid task card suitable for browser authoring."""
    node = node_template("task", index)
    node.update(
        title=f"New task {index}",
        description="Describe the outcome this card must produce.",
        outputs={
            "summary": {"type": "markdown", "description": "Completion summary and evidence."}
        },
        success={
            "summary": "The card completed and produced a summary.",
            "criteria": [
                {
                    "id": "summary_present",
                    "kind": "artifact_present",
                    "description": "A completion summary was emitted.",
                    "output": "summary",
                }
            ],
        },
    )
    return node


async def generate_web_graph(
    goal: str,
    *,
    project: str | Path,
    username: str,
    progress: Any = None,
) -> dict[str, Any]:
    """Generate a review-only graph proposal using the configured planning model."""
    objective = goal.strip()
    if not objective:
        return {"ok": False, "error": "Describe a goal before generating a graph"}
    return await model_graph_draft(
        objective,
        project=project,
        config=load_config(username),
        instruction=(
            "Create a concise dependency graph of executable task cards for this goal. "
            "Every task must have a clear title, instructions, outputs, and success criteria."
        ),
        progress=progress,
    )


class GraphDraftManager:
    """Generate graph proposals in background jobs with safe progress events."""

    def __init__(self, project: str | Path, username: str):
        self.project = Path(project).resolve()
        self.username = username
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, goal: str) -> dict[str, Any]:
        objective = goal.strip()
        if not objective:
            return {"ok": False, "error": "Describe a goal before generating a graph"}
        job_id = uuid.uuid4().hex
        job = {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "message": "Graph generation is queued.",
            "started_at": time.time(),
            "activity": [],
        }
        with self._lock:
            if len(self._jobs) >= 20:
                oldest = min(self._jobs, key=lambda key: self._jobs[key]["started_at"])
                self._jobs.pop(oldest, None)
            self._jobs[job_id] = job
        threading.Thread(target=self._run, args=(job_id, objective), daemon=True).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"ok": False, "error": "Graph generation job was not found"}
            return {
                key: value
                for key, value in job.items()
                if key not in {"started_at", "loop", "task"}
            }

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"ok": False, "error": "Graph generation job was not found"}
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                return {
                    key: value
                    for key, value in job.items()
                    if key not in {"started_at", "loop", "task"}
                }
            job.update(
                status="cancelled",
                stage="cancelled",
                message="Graph generation was cancelled.",
                result={"ok": False, "error": "Graph generation was cancelled."},
            )
            loop = job.get("loop")
            task = job.get("task")
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)
        return self.status(job_id)

    def _progress(self, job_id: str, event: dict[str, Any]) -> None:
        item = {**event, "at": time.time()}
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job["status"] == "cancelled":
                return
            job["status"] = "running"
            job["stage"] = str(event.get("stage") or "running")
            job["message"] = str(event.get("message") or "Generating graph…")
            job["activity"] = [*job["activity"], item][-40:]

    def _run(self, job_id: str, goal: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(
                generate_web_graph(
                    goal,
                    project=self.project,
                    username=self.username,
                    progress=lambda event: self._progress(job_id, event),
                )
            )
            with self._lock:
                job = self._jobs[job_id]
                job.update(loop=loop, task=task)
                cancelled = job["status"] == "cancelled"
            if cancelled:
                task.cancel()
            result = loop.run_until_complete(task)
            with self._lock:
                job = self._jobs[job_id]
                if job["status"] == "cancelled":
                    return
                job["result"] = result
                job["status"] = "succeeded" if result.get("ok") else "failed"
                job["stage"] = "complete" if result.get("ok") else "failed"
                job["message"] = (
                    "Graph generation completed."
                    if result.get("ok")
                    else str(result.get("error") or "Graph generation failed")
                )
        except asyncio.CancelledError:
            return
        except Exception as error:  # noqa: BLE001 - returned to the loopback UI
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "failed"
                job["stage"] = "failed"
                job["message"] = str(error)
                job["result"] = {"ok": False, "error": str(error)}
        finally:
            with self._lock:
                stored_job = self._jobs.get(job_id)
                if stored_job:
                    stored_job.pop("task", None)
                    stored_job.pop("loop", None)
            loop.close()


def preview_web_graph(
    document: dict[str, Any], *, project: str | Path, username: str
) -> dict[str, Any]:
    if not isinstance(document, dict):
        return {"ok": False, "error": "document must be an object"}
    result = preview_graph(document, project=project, config=load_config(username))
    return _with_validation_error(result)


def save_web_graph(
    document: dict[str, Any],
    raw_path: str,
    *,
    project: str | Path,
    username: str,
    expected_digest: str = "",
) -> dict[str, Any]:
    target = confined_graph_target(project, raw_path)
    result = save_graph(
        document,
        target,
        project=project,
        config=load_config(username),
        expected_digest=expected_digest,
    )
    return _with_validation_error(result)


def _with_validation_error(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("ok") or result.get("error"):
        return result
    findings = (result.get("validation") or {}).get("findings") or []
    messages = [
        str(item.get("message") or "").strip()
        for item in findings
        if item.get("severity") == "error"
    ]
    result["error"] = (
        "; ".join(message for message in messages[:4] if message) or "Graph validation failed"
    )
    return result


def confined_graph_path(project: str | Path, raw_path: str) -> Path:
    root = Path(project).resolve()
    candidate = Path(raw_path).expanduser()
    candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("graph path must stay inside the selected project")
    if not candidate.is_file():
        raise ValueError("graph file does not exist")
    if not candidate.name.lower().endswith(GRAPH_SUFFIXES):
        raise ValueError("graph must use .agraph.yaml, .agraph.yml, or .agraph.json")
    return candidate


def read_web_graph(raw_path: str, *, project: str | Path = ".") -> dict[str, Any]:
    """Return a saved graph's raw document, for editing or export.

    The board needs the document itself, not the execution plan: adding a card
    to a plan would lose everything the plan does not carry.
    """
    try:
        path = confined_graph_path(project, raw_path)
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    if not path.is_file():
        return {"ok": False, "error": f"No graph at {raw_path}"}
    try:
        document = dict(load_graph(path).data)
    except Exception as error:  # noqa: BLE001 - surfaced to the client
        return {"ok": False, "error": str(error)}
    return {
        "ok": True,
        "path": str(path.relative_to(Path(project).resolve())),
        "document": document,
    }


def graph_catalog(store: WorkbenchStore, project: str | Path) -> dict[str, Any]:
    root = Path(project).resolve()
    found: dict[str, dict[str, Any]] = {}
    for item in store.read("graphs", []):
        raw = str(item.get("path") or "")
        try:
            path = confined_graph_path(root, raw)
        except ValueError:
            continue
        found[str(path)] = {
            "path": str(path),
            "name": path.name,
            "graph_id": str(item.get("graph_id") or path.stem),
            "source": "catalogue",
        }
    ignored = {".git", ".magent", "node_modules", "target", "dist", ".venv", "venv"}
    try:
        candidates = root.rglob("*")
        for path in candidates:
            if len(found) >= 100:
                break
            relative = path.relative_to(root)
            if any(part in ignored for part in relative.parts):
                continue
            if path.is_file() and path.name.lower().endswith(GRAPH_SUFFIXES):
                resolved = path.resolve()
                found.setdefault(
                    str(resolved),
                    {
                        "path": str(resolved),
                        "name": resolved.name,
                        "graph_id": resolved.name.split(".agraph", 1)[0],
                        "source": "project",
                    },
                )
    except OSError:
        pass
    runs = []
    for item in reversed(store.read("graph_runs", [])):
        runs.append(
            {
                "run_id": str(item.get("run_id") or ""),
                "graph_id": str(item.get("graph_id") or ""),
                "status": str(item.get("status") or ""),
                "started_at": str(item.get("started_at") or ""),
                "finished_at": str(item.get("finished_at") or ""),
                "summary": item.get("summary") or {},
            }
        )
        if len(runs) >= 30:
            break
    return {
        "ok": True,
        "graphs": sorted(found.values(), key=lambda item: item["name"]),
        "runs": runs,
    }


class GraphRunManager:
    """Own background graph runs and expose polling-friendly Kanban snapshots."""

    def __init__(self, store: WorkbenchStore, username: str, project: str | Path):
        self.store = store
        self.username = username
        self.project = Path(project).resolve()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def preview(self, raw_path: str) -> dict[str, Any]:
        path = confined_graph_path(self.project, raw_path)
        return {
            "ok": True,
            "path": str(path),
            "plan": resolved_plan(
                str(path),
                project=str(self.project),
                config=load_config(self.username),
            ),
        }

    def start(
        self,
        raw_path: str,
        *,
        params: dict[str, Any] | None = None,
        approved_gates: list[str] | None = None,
    ) -> dict[str, Any]:
        preview = self.preview(raw_path)
        path = Path(preview["path"])
        plan = preview["plan"]
        approved = {str(item) for item in (approved_gates or [])}
        missing_gates = sorted(set(plan.get("gates") or []) - approved)
        if missing_gates:
            raise ValueError("review and approve gates before running: " + ", ".join(missing_gates))
        job_id = f"webgraph_{uuid.uuid4().hex[:16]}"
        job = {
            "ok": True,
            "job_id": job_id,
            "run_id": "",
            "path": str(path),
            "graph_id": str(plan.get("graph_id") or path.stem),
            "graph_digest": str(plan.get("graph_digest") or ""),
            "state": "queued",
            "summary": "Waiting for the graph runner.",
            "activity": "Queued for the graph runner.",
            "plan": plan,
            "events": [],
            "nodes": [
                {
                    "node_id": item["id"],
                    "title": item.get("title") or item["id"],
                    "type": item.get("type", "task"),
                    "profile": item.get("agent_profile")
                    or (item.get("resolved_profile") or {}).get("name", ""),
                    "dependencies": item.get("dependencies") or [],
                    "state": "pending",
                    "summary": "",
                    "error": "",
                    "files_changed": [],
                }
                for item in plan.get("nodes") or []
            ],
        }
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(
            target=self._execute,
            args=(job_id, path, dict(params or {}), approved),
            daemon=True,
        )
        thread.start()
        return self.status(job_id) or job

    def status(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            snapshot = dict(job) if job else None
            if snapshot is not None and job is not None:
                snapshot["events"] = list(job.get("events") or [])[-500:]
                snapshot["nodes"] = [dict(item) for item in job.get("nodes") or []]
        if not snapshot:
            durable = graph_status(self.store, job_id)
            return durable
        run_id = str(snapshot.get("run_id") or "")
        durable = graph_status(self.store, run_id) if run_id else None
        if durable:
            snapshot.update(
                state=durable.get("state") or snapshot["state"],
                summary=(durable.get("summary") or {}).get("text")
                or durable.get("summary")
                or snapshot["summary"],
                nodes=durable.get("nodes") or snapshot["nodes"],
            )
        return snapshot

    def _execute(self, job_id: str, path: Path, params: dict[str, Any], approved: set[str]) -> None:
        def emit(event: dict[str, Any]) -> None:
            with self._lock:
                job = self._jobs[job_id]
                job["events"].append(event)
                job["run_id"] = str(event.get("run_id") or job["run_id"])
                if event.get("type") == "graph.started":
                    job["state"] = "running"
                    job["summary"] = str(event.get("summary") or "Graph execution started.")
                job["activity"] = _graph_event_activity(event)
                if event.get("node_id"):
                    node = next(
                        (item for item in job["nodes"] if item["node_id"] == event["node_id"]),
                        None,
                    )
                    if node:
                        node.update(
                            state=str(event.get("state") or node["state"]),
                            summary=str(event.get("summary") or node["summary"]),
                            error=str(event.get("error") or node["error"]),
                            files_changed=list(event.get("files_changed") or node["files_changed"]),
                        )
                if event.get("type") == "graph.completed":
                    job["state"] = str(event.get("state") or "completed")
                    job["summary"] = str(event.get("summary") or "Graph execution completed.")

        async def approve(_prompt: str, detail: dict[str, Any]) -> bool:
            return str(detail.get("node_id") or "") in approved

        async def run() -> dict[str, Any]:
            executor = GraphExecutor(
                username=self.username,
                config=load_config(self.username),
                project=self.project,
                store=self.store,
                approval=approve,
                event_sink=emit,
            )
            return await executor.run(path, params=params)

        try:
            result = asyncio.run(run())
            record = result.get("run") or {}
            with self._lock:
                job = self._jobs[job_id]
                job["run_id"] = str(record.get("run_id") or job["run_id"])
                job["state"] = str(
                    record.get("status") or ("succeeded" if result.get("ok") else "failed")
                )
                summary = record.get("summary") or {}
                job["summary"] = str(summary.get("text") or summary or job["summary"])
        except BaseException as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["state"] = "failed"
                job["summary"] = str(exc)
                job["activity"] = f"Graph runner failed: {str(exc)[:240]}"


def _graph_event_activity(event: dict[str, Any]) -> str:
    """Return a concise, non-sensitive description for the live graph health UI."""
    kind = str(event.get("type") or "graph.event")
    title = str(event.get("title") or event.get("node_id") or "the graph")
    state = str(event.get("state") or "active")
    if kind == "graph.started":
        return "Graph execution started; finding the first ready card."
    if kind == "node.started":
        attempt = int(event.get("attempt") or 1)
        return f"Running {title} (attempt {attempt})."
    if kind == "node.tool.requested":
        return f"{title} requested the declared tool {event.get('tool', 'unknown')}."
    if kind == "node.completed":
        error = str(event.get("error") or "").strip()
        suffix = f" {error[:180]}" if error else ""
        return f"{title} finished with status {state}.{suffix}"
    if kind == "graph.completed":
        return f"Graph execution finished with status {state}."
    return str(event.get("summary") or f"{title}: {kind} ({state}).")[:240]
