"""Real agent evaluation harness with isolated workspaces and independent validators."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import tempfile
import time
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from magent.ask_audit import audit_one_shot_task
from magent.config import DEFAULT_GLOBAL_CONFIG, Config, get_current_user, load_config
from magent.providers import Provider
from magent.session_controls import session_usage
from magent.workbench_store import now_iso

AGENT_EVAL_SCHEMA = "magent.agent-eval.v1"
AGENT_EVAL_REPORT_SCHEMA = "magent.agent-eval-report.v1"


class AgentEvalRunner(Protocol):
    """Injectable task runner used by tests and external harnesses."""

    def __call__(
        self,
        task: dict[str, Any],
        workspace: Path,
        *,
        provider_id: str,
        model: str,
        timeout_seconds: int,
    ) -> dict[str, Any]: ...


class _EvalMessage:
    def __init__(self, content: str = "", tool_calls: list[Any] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ],
        }


def _script_response(step: dict[str, Any], index: int) -> Any:
    tool_name = str(step.get("tool") or "")
    calls: list[Any] = []
    if tool_name:
        arguments = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        calls.append(
            SimpleNamespace(
                id=f"eval_call_{index}",
                function=SimpleNamespace(name=tool_name, arguments=json.dumps(arguments)),
            )
        )
    usage = step.get("usage") if isinstance(step.get("usage"), dict) else {}
    return SimpleNamespace(
        choices=[SimpleNamespace(message=_EvalMessage(str(step.get("content") or ""), calls))],
        usage=(
            SimpleNamespace(
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
            )
            if usage
            else None
        ),
    )


def _eval_config() -> Config:
    raw = deepcopy(DEFAULT_GLOBAL_CONFIG)
    raw["memory"].update({"auto_write": False, "write_every_n_turns": 0, "semantic_enabled": False})
    raw["session_messaging"]["enabled"] = False
    raw["ui"].update({"show_tool_calls": False, "stream_output": False})
    raw["agent"]["selective_tools"] = False
    return Config(raw, {"permissions": {"mode": "yolo"}}, username=None)


def _live_config() -> Config:
    username = get_current_user()
    if not username:
        raw = deepcopy(DEFAULT_GLOBAL_CONFIG)
        raw.setdefault("memory", {}).update(
            {"auto_write": False, "write_every_n_turns": 0, "semantic_enabled": False}
        )
        raw.setdefault("session_messaging", {})["enabled"] = False
        raw.setdefault("ui", {}).update({"show_tool_calls": False, "stream_output": False})
        return Config(raw, {"permissions": {"mode": "yolo"}}, username=None)
    source = load_config(username)
    raw = deepcopy(source._global)
    user = deepcopy(source._user)
    raw.setdefault("memory", {}).update(
        {"auto_write": False, "write_every_n_turns": 0, "semantic_enabled": False}
    )
    raw.setdefault("session_messaging", {})["enabled"] = False
    raw.setdefault("ui", {}).update({"show_tool_calls": False, "stream_output": False})
    user.setdefault("memory", {}).update(
        {"auto_write": False, "write_every_n_turns": 0, "semantic_enabled": False}
    )
    return Config(raw, user, username=None)


def _provider_for(config: Config, provider_id: str, model: str) -> Provider:
    selected_provider = provider_id or config.default_provider
    selected_model = model or config.default_model
    return Provider(
        selected_provider,
        selected_model,
        config.resolve_api_key(selected_provider),
        config.provider_config(selected_provider),
    )


def _run_agent_task_inner(
    task: dict[str, Any],
    workspace: Path,
    *,
    provider_id: str = "",
    model: str = "",
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Run one task through AgentSession and return execution evidence."""
    from magent.agent import AgentSession

    script = task.get("script") if isinstance(task.get("script"), list) else []
    config = _eval_config() if script else _live_config()
    provider = _provider_for(config, provider_id, model)
    username = get_current_user() or "eval"
    first_activity_at: float | None = None
    events: list[dict[str, Any]] = []
    started = time.perf_counter()

    class EvalSession(AgentSession):
        async def _model_round(self, messages: list[dict[str, Any]], tool_defs: Any, **kwargs: Any) -> Any:
            del messages, tool_defs, kwargs
            if not script:
                return await super()._model_round([], None)
            index = int(getattr(self, "_eval_script_index", 0))
            if index >= len(script):
                return _script_response({"content": "Evaluation script completed."}, index)
            self._eval_script_index = index + 1
            return _script_response(script[index], index)

    session_class = EvalSession if script else AgentSession
    session = session_class(
        username=username,
        config=config,
        provider=provider,
        extraction_provider=provider,
        cwd=str(workspace),
        interactive_permissions=False,
        permission_mode_override=str(task.get("permission_mode") or "yolo"),
    )
    # Agent evals measure execution, not the user's persistent graph. Avoid a
    # session-summary write and keep each fixture hermetic.
    index = getattr(session.memory, "_index", None)
    if index is not None and hasattr(index, "close"):
        with contextlib.suppress(Exception):
            index.close()
    session.memory._index = None

    def capture(event: dict[str, Any]) -> None:
        nonlocal first_activity_at
        events.append(event)
        if first_activity_at is None and event.get("event") in {
            "activity_event",
            "timing",
            "tool_call",
        }:
            first_activity_at = time.perf_counter()

    session.logger.set_event_callback(capture)

    async def execute() -> str:
        try:
            return await asyncio.wait_for(
                session.chat(str(task.get("prompt") or "")), timeout=max(1, timeout_seconds)
            )
        finally:
            await session.end_session()
            current = asyncio.current_task()
            pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
            for background in pending:
                background.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    error = ""
    response = ""
    try:
        response = asyncio.run(execute())
    except TimeoutError:
        error = f"Agent task timed out after {timeout_seconds}s"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        session.logger.close()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    usage = session_usage(session.logger.path)
    audit = audit_one_shot_task(str(task.get("prompt") or ""), workspace, session.scratchpad)
    return {
        "ok": not error,
        "response": response,
        "error": error[:1000],
        "provider": provider.provider_id,
        "model": provider.model,
        "session_id": session.session_id,
        "elapsed_ms": elapsed_ms,
        "time_to_first_activity_ms": (
            round((first_activity_at - started) * 1000, 2) if first_activity_at else None
        ),
        "tool_calls": int(usage.get("tool_calls") or 0),
        "retries": sum(
            1
            for event in events
            if event.get("event") == "activity_event"
            and event.get("type") in {"tool_retry", "artifact_recovery"}
        ),
        "usage": {
            key: usage.get(key, 0)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cached_tokens",
                "cost_usd",
            )
        },
        "changed_files": sorted(str(path) for path in session.scratchpad.get("files_touched", [])),
        "audit": audit,
        "events": events,
    }


@contextlib.contextmanager
def _isolated_agent_paths(workspace: Path):
    """Keep eval logs and memory out of the user's real MagAgent state."""
    import magent.agent as agent_module
    import magent.config as config_module
    import magent.logging as logging_module

    state = workspace / ".magent-eval"
    logs = state / "logs"
    memory = state / "memory"
    logs.mkdir(parents=True, exist_ok=True)
    memory.mkdir(parents=True, exist_ok=True)
    old_config_logs = config_module.LOGS_DIR
    old_logging_logs = logging_module.LOGS_DIR
    old_memory_dir = agent_module.user_memory_dir
    old_hooks = agent_module.run_hooks_async
    console_capture = agent_module.console.capture()

    async def no_hooks(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def eval_memory_dir(username: str) -> Path:
        del username
        return memory

    config_module.LOGS_DIR = logs
    logging_module.LOGS_DIR = logs
    agent_module.user_memory_dir = eval_memory_dir
    agent_module.run_hooks_async = no_hooks
    console_capture.__enter__()
    try:
        yield
    finally:
        console_capture.__exit__(None, None, None)
        config_module.LOGS_DIR = old_config_logs
        logging_module.LOGS_DIR = old_logging_logs
        agent_module.user_memory_dir = old_memory_dir
        agent_module.run_hooks_async = old_hooks


def run_agent_task(
    task: dict[str, Any],
    workspace: Path,
    *,
    provider_id: str = "",
    model: str = "",
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Run one task without mutating the user's logs or memory graph."""
    with _isolated_agent_paths(workspace):
        return _run_agent_task_inner(
            task,
            workspace,
            provider_id=provider_id,
            model=model,
            timeout_seconds=timeout_seconds,
        )


def run_agent_eval_suite(
    root: str | Path,
    suite_path: str | Path,
    *,
    store: Any | None = None,
    runner: AgentEvalRunner | None = None,
    provider_id: str = "",
    model: str = "",
    timeout_seconds: int = 180,
    keep_workspaces: bool = False,
) -> dict[str, Any]:
    """Run a versioned real-agent suite in isolated workspaces."""
    root_path = Path(root).resolve()
    path = Path(suite_path)
    if not path.is_absolute():
        path = root_path / path
    suite = json.loads(path.read_text(encoding="utf-8"))
    if suite.get("schema") != AGENT_EVAL_SCHEMA:
        raise ValueError(f"Expected schema {AGENT_EVAL_SCHEMA!r}")
    tasks = suite.get("tasks") if isinstance(suite.get("tasks"), list) else []
    task_runner = runner or run_agent_task
    run_root = Path(tempfile.mkdtemp(prefix="magent-agent-eval-"))
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        for index, task in enumerate(tasks, start=1):
            if not isinstance(task, dict):
                continue
            workspace = run_root / f"{index:03d}-{_safe_name(str(task.get('id') or 'task'))}"
            workspace.mkdir(parents=True, exist_ok=True)
            _prepare_workspace(workspace, task, path.parent)
            task_started = time.perf_counter()
            try:
                execution = task_runner(
                    task,
                    workspace,
                    provider_id=str(task.get("provider") or provider_id),
                    model=str(task.get("model") or model),
                    timeout_seconds=int(task.get("timeout_seconds") or timeout_seconds),
                )
            except Exception as exc:
                execution = {
                    "ok": False,
                    "response": "",
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                    "usage": {},
                    "audit": {},
                    "events": [],
                }
            execution = _sanitize_workspace_paths(execution, workspace)
            execution = _sanitize_workspace_paths(execution, run_root)
            validations = _validate_task(task, workspace, execution)
            ok = bool(execution.get("ok")) and all(item["ok"] for item in validations)
            results.append(
                {
                    "id": str(task.get("id") or f"task-{index}"),
                    "category": str(task.get("category") or "general"),
                    "prompt": str(task.get("prompt") or ""),
                    "ok": ok,
                    "artifact_task": bool(task.get("artifact_task")),
                    "workspace": str(workspace) if keep_workspaces else "",
                    "elapsed_ms": round((time.perf_counter() - task_started) * 1000, 2),
                    "execution": execution,
                    "validations": validations,
                }
            )
    finally:
        if not keep_workspaces:
            shutil.rmtree(run_root, ignore_errors=True)

    passed = sum(1 for result in results if result["ok"])
    artifacts = [result for result in results if result["artifact_task"]]
    artifact_passed = sum(1 for result in artifacts if result["ok"])
    success_rate = passed / len(results) if results else 0.0
    artifact_success_rate = artifact_passed / len(artifacts) if artifacts else 1.0
    targets = suite.get("targets") if isinstance(suite.get("targets"), dict) else {}
    target_success = float(targets.get("success_rate") or 1.0)
    target_artifacts = float(targets.get("artifact_success_rate") or 1.0)
    report = {
        "schema": AGENT_EVAL_REPORT_SCHEMA,
        "ok": success_rate >= target_success and artifact_success_rate >= target_artifacts,
        "suite": str(suite.get("name") or path.stem),
        "suite_schema": AGENT_EVAL_SCHEMA,
        "suite_path": str(path),
        "version": _current_version(),
        "ran_at": now_iso(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "passed": passed,
        "total": len(results),
        "success_rate": round(success_rate, 4),
        "artifact_passed": artifact_passed,
        "artifact_total": len(artifacts),
        "artifact_success_rate": round(artifact_success_rate, 4),
        "targets": {
            "success_rate": target_success,
            "artifact_success_rate": target_artifacts,
        },
        "metrics": _aggregate_metrics(results),
        "tasks": results,
    }
    if store is not None:
        store.append("agent_eval_runs", report)
    return report


def _prepare_workspace(workspace: Path, task: dict[str, Any], suite_dir: Path) -> None:
    fixture = str(task.get("fixture") or "")
    if fixture:
        source = (suite_dir / fixture).resolve()
        if not source.is_dir():
            raise FileNotFoundError(source)
        shutil.copytree(source, workspace, dirs_exist_ok=True)
    raw_files = task.get("files")
    files: dict[Any, Any] = raw_files if isinstance(raw_files, dict) else {}
    for relative, content in files.items():
        target = _contained(workspace, str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")


def _validate_task(
    task: dict[str, Any], workspace: Path, execution: dict[str, Any]
) -> list[dict[str, Any]]:
    raw_validators = task.get("validators")
    validators: list[Any] = raw_validators if isinstance(raw_validators, list) else []
    results: list[dict[str, Any]] = []
    for validator in validators:
        if not isinstance(validator, dict):
            results.append({"ok": False, "type": "invalid", "error": "validator must be an object"})
            continue
        kind = str(validator.get("type") or "")
        try:
            if kind == "file_exists":
                target = _contained(workspace, str(validator.get("path") or ""))
                ok = target.is_file()
                detail = {"path": str(validator.get("path") or ""), "exists": ok}
            elif kind == "file_contains":
                target = _contained(workspace, str(validator.get("path") or ""))
                needle = str(validator.get("text") or "")
                ok = target.is_file() and needle in target.read_text(encoding="utf-8", errors="replace")
                detail = {"path": str(validator.get("path") or ""), "contains": needle[:200]}
            elif kind == "file_min_bytes":
                target = _contained(workspace, str(validator.get("path") or ""))
                minimum = max(0, int(validator.get("min_bytes") or 1))
                size = target.stat().st_size if target.is_file() else 0
                ok = size >= minimum
                detail = {"path": str(validator.get("path") or ""), "bytes": size, "minimum": minimum}
            elif kind == "json_valid":
                target = _contained(workspace, str(validator.get("path") or ""))
                json.loads(target.read_text(encoding="utf-8"))
                ok, detail = True, {"path": str(validator.get("path") or "")}
            elif kind == "zip_contains":
                target = _contained(workspace, str(validator.get("path") or ""))
                member = str(validator.get("member") or "")
                with zipfile.ZipFile(target) as archive:
                    names = archive.namelist()
                ok = member in names
                detail = {"path": str(validator.get("path") or ""), "member": member}
            elif kind == "response_contains":
                needle = str(validator.get("text") or "")
                ok = needle.lower() in str(execution.get("response") or "").lower()
                detail = {"contains": needle[:200]}
            elif kind == "audit_ok":
                ok = bool((execution.get("audit") or {}).get("ok"))
                detail = {"audit": execution.get("audit") or {}}
            elif kind == "permission_failure":
                failures = list((execution.get("audit") or {}).get("permission_failures") or [])
                ok = bool(failures)
                detail = {"permission_failures": failures}
            else:
                ok, detail = False, {"error": f"unknown validator type: {kind}"}
        except Exception as exc:
            ok, detail = False, {"error": f"{type(exc).__name__}: {exc}"}
        results.append({"type": kind, "ok": ok, **detail})
    return results


def _aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    executions = [result.get("execution") or {} for result in results]
    usage_keys = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "cost_usd")
    return {
        "elapsed_ms": round(sum(float(item.get("elapsed_ms") or 0) for item in executions), 2),
        "tool_calls": sum(int(item.get("tool_calls") or 0) for item in executions),
        "retries": sum(int(item.get("retries") or 0) for item in executions),
        "time_to_first_activity_ms": _average(
            [item.get("time_to_first_activity_ms") for item in executions]
        ),
        **{
            key: round(sum(float((item.get("usage") or {}).get(key) or 0) for item in executions), 6)
            for key in usage_keys
        },
    }


def _sanitize_workspace_paths(value: Any, workspace: Path) -> Any:
    """Remove random temporary roots while preserving useful task evidence."""
    if isinstance(value, dict):
        return {key: _sanitize_workspace_paths(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_workspace_paths(item, workspace) for item in value]
    if isinstance(value, str):
        return value.replace(str(workspace), ".")
    return value


def _average(values: list[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _contained(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("eval paths must be non-empty and relative")
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"eval path escapes workspace: {relative}")
    return target


def _safe_name(value: str) -> str:
    text = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    return text.strip("-")[:80] or "task"


def _current_version() -> str:
    with contextlib.suppress(Exception):
        from magent import __version__

        return str(__version__)
    return ""


def write_agent_eval_report(report: dict[str, Any], path: str | Path) -> str:
    """Write a machine-readable report atomically."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(target)
    return str(target)


def compact_agent_eval_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return release-sized evidence while retaining outcomes and diagnostics."""
    compact = deepcopy(report)
    for task in compact.get("tasks", []):
        execution = task.get("execution") if isinstance(task, dict) else None
        if not isinstance(execution, dict):
            continue
        execution.pop("events", None)
        execution.pop("session_id", None)
        response = str(execution.get("response") or "")
        if len(response) > 1000:
            execution["response"] = response[:1000] + "..."
    return compact
