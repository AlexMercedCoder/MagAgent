"""Harness-owned AGS success criterion evaluation."""

from __future__ import annotations

import json
import re
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from magent.agraph.expressions import evaluate_expression, resolve_value

CommandRunner = Callable[[str, int, str], Awaitable[dict[str, Any]]]
ApprovalCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]
JudgeCallback = Callable[[str, list[Any], dict[str, Any]], Awaitable[tuple[float, str]]]
ExternalChecker = Callable[[dict[str, Any], dict[str, Any]], Awaitable[tuple[bool, str]]]

EXTERNAL_CHECKERS: dict[str, ExternalChecker] = {}


def register_external_checker(name: str, checker: ExternalChecker) -> None:
    EXTERNAL_CHECKERS[name] = checker


@dataclass(frozen=True)
class CriterionResult:
    id: str
    kind: str
    severity: str
    passed: bool
    evidence: str = ""
    score: float | None = None
    error: str = ""
    duration_seconds: float = 0.0
    evaluated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return {key: item for key, item in value.items() if item not in {None, ""}}


async def evaluate_criteria(
    criteria: list[dict[str, Any]],
    *,
    outputs: dict[str, Any],
    scope: dict[str, Any],
    project: Path,
    command_runner: CommandRunner | None = None,
    approval: ApprovalCallback | None = None,
    judge: JudgeCallback | None = None,
    mode: str = "all",
    count: int = 1,
) -> tuple[bool, list[CriterionResult]]:
    results = []
    for criterion in criteria:
        results.append(
            await evaluate_criterion(
                criterion,
                outputs=outputs,
                scope=scope,
                project=project,
                command_runner=command_runner,
                approval=approval,
                judge=judge,
            )
        )
    required = [item for item in results if item.severity == "required"]
    successes = sum(item.passed for item in required)
    if mode == "any":
        passed = not required or successes >= 1
    elif mode == "n_of":
        passed = successes >= count
    else:
        passed = successes == len(required)
    return passed, results


async def evaluate_criterion(
    criterion: dict[str, Any],
    *,
    outputs: dict[str, Any],
    scope: dict[str, Any],
    project: Path,
    command_runner: CommandRunner | None = None,
    approval: ApprovalCallback | None = None,
    judge: JudgeCallback | None = None,
) -> CriterionResult:
    started = time.monotonic()
    criterion_id = str(criterion.get("id", "criterion"))
    kind = str(criterion.get("kind", ""))
    severity = str(criterion.get("severity", "required"))
    evidence = ""
    score: float | None = None
    error = ""
    passed = False
    try:
        if kind == "command":
            if command_runner is None:
                raise RuntimeError("command criteria are unavailable")
            timeout = int(criterion.get("timeout_seconds", 60) or 60)
            command = str(resolve_value(criterion.get("run", ""), scope))
            result = await command_runner(command, timeout, str(criterion.get("cwd", "")))
            expected = int(criterion.get("expect_exit_code", 0))
            passed = int(result.get("returncode", -1)) == expected
            stdout = str(result.get("stdout", ""))
            pattern = criterion.get("expect_stdout_matches")
            if pattern:
                passed = passed and re.search(str(pattern), stdout) is not None
            evidence = (stdout + "\n" + str(result.get("stderr", ""))).strip()[-4000:]
        elif kind == "file_exists":
            pattern = str(resolve_value(criterion.get("path", ""), scope))
            matches = _safe_glob(project, pattern)
            minimum = int(criterion.get("min_bytes", 0) or 0)
            passed = bool(matches) and all(path.is_file() and path.stat().st_size >= minimum for path in matches)
            evidence = ", ".join(str(path.relative_to(project)) for path in matches[:20])
        elif kind == "artifact_present":
            name = str(criterion.get("output", ""))
            passed = name in outputs and outputs[name] is not None and outputs[name] != ""
            evidence = _evidence(outputs.get(name))
        elif kind == "expression":
            value = evaluate_expression(str(criterion.get("expr", "")), {**scope, "self": {"outputs": outputs}})
            if not isinstance(value, bool):
                raise ValueError("expression criterion must evaluate to boolean")
            passed = value
            evidence = str(value).lower()
        elif kind == "regex":
            if criterion.get("target"):
                target = evaluate_expression(str(criterion["target"]), {**scope, "self": {"outputs": outputs}})
            else:
                target = outputs.get(str(criterion.get("output", "")), "")
            flags = sum((getattr(re, flag.upper()) for flag in str(criterion.get("flags", ""))), re.NOFLAG)
            matched = re.search(str(criterion.get("pattern", "")), str(target), flags) is not None
            passed = not matched if criterion.get("negate") else matched
            evidence = _evidence(target)
        elif kind == "json_schema":
            value = outputs.get(str(criterion.get("output", "")))
            schema = criterion.get("schema")
            if schema is None:
                schema_path = _safe_path(project, str(criterion.get("schema_ref", "")))
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(value)
            passed = True
            evidence = "valid"
        elif kind == "human":
            if approval is None:
                raise RuntimeError("RT015 human review cannot be presented")
            passed = await approval(str(resolve_value(criterion.get("prompt", criterion.get("description", "Approve?")), scope)), criterion)
            evidence = "approved" if passed else "rejected"
        elif kind == "llm_judge":
            if judge is None:
                raise RuntimeError("llm judge is unavailable")
            samples = max(1, int(criterion.get("samples", 1) or 1))
            inputs = [resolve_value(value, {**scope, "self": {"outputs": outputs}}) for value in criterion.get("inputs") or list(outputs.values())]
            judgments = [await judge(str(resolve_value(criterion.get("rubric", ""), scope)), inputs, criterion) for _ in range(samples)]
            score = float(statistics.median(item[0] for item in judgments))
            passed = score >= float(criterion.get("threshold", 0.8))
            evidence = " | ".join(item[1] for item in judgments)[-4000:]
        elif kind == "external":
            checker = EXTERNAL_CHECKERS.get(str(criterion.get("check", "")))
            if checker is None:
                raise RuntimeError(f"external checker {criterion.get('check')!r} is not registered")
            passed, evidence = await checker(criterion.get("params") or {}, {**scope, "self": {"outputs": outputs}})
        else:
            raise ValueError(f"unsupported criterion kind {kind!r}")
    except Exception as exc:
        error = str(exc)
        passed = False
    return CriterionResult(
        criterion_id,
        kind,
        severity,
        passed,
        evidence=evidence if criterion.get("record_evidence", True) else "",
        score=score,
        error=error,
        duration_seconds=round(time.monotonic() - started, 6),
        evaluated_at=datetime.now(UTC).isoformat(),
    )


def _safe_path(project: Path, raw: str) -> Path:
    path = (project / raw).resolve(strict=False)
    if path != project and project not in path.parents:
        raise ValueError("path escapes the graph workspace")
    return path


def _safe_glob(project: Path, pattern: str) -> list[Path]:
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ValueError("path escapes the graph workspace")
    return [path.resolve() for path in project.glob(pattern) if path.resolve() == project or project in path.resolve().parents]


def _evidence(value: Any) -> str:
    try:
        return json.dumps(value, default=str)[:4000]
    except Exception:
        return str(value)[:4000]
