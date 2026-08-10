"""Per-provider conformance checks.

Bugs #24 and #26 were both provider-shaped and both invisible to the test
suite: a keyring credential that no readiness check looked at, and a hardcoded
temperature the provider layer specifically works around. Neither needed a live
API call to catch — they are contract questions about how MagAgent talks to a
provider, so they are checked here against recorded fixtures and run in CI.

`--live` re-runs the same checks against configured providers, which is how the
fixtures get refreshed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "CONFORMANCE_CHECKS",
    "conformance_matrix",
    "fixture_path",
    "load_fixtures",
    "record_fixture",
]

# Providers whose quirks the provider layer encodes. Each entry is what we
# assert MagAgent does, not what the vendor documents.
CONFORMANCE_CHECKS: list[dict[str, Any]] = [
    {
        "id": "default-temperature-only",
        "description": "Models that reject a custom temperature must not receive one.",
        "cases": [
            {"provider": "openai", "model": "gpt-5.1", "temperature": 0.3, "expect_temperature": None},
            {"provider": "openai", "model": "gpt-5.1", "temperature": 1, "expect_temperature": 1},
            {"provider": "anthropic", "model": "claude-sonnet-5", "temperature": 0.3, "expect_temperature": None},
            {"provider": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.3, "expect_temperature": 0.3},
            {"provider": "google", "model": "gemini-3-pro", "temperature": 0.3, "expect_temperature": None},
            {"provider": "openai", "model": "gpt-4o", "temperature": 0.3, "expect_temperature": 0.3},
        ],
    },
    {
        "id": "request-deadline",
        "description": "Every provider call carries a timeout.",
        "cases": [
            {"provider": "openai", "model": "gpt-4o", "temperature": 0.3, "expect_timeout": True},
            {"provider": "anthropic", "model": "claude-sonnet-5", "temperature": 0.3, "expect_timeout": True},
        ],
    },
]


def fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "provider_conformance.json"


def load_fixtures() -> dict[str, Any]:
    path = fixture_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def record_fixture(matrix: dict[str, Any]) -> Path:
    """Write the current matrix as the recorded baseline."""
    path = fixture_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    from magent.providers import _completion_request_params

    params = _completion_request_params(
        case["provider"], case["model"], case["temperature"], 1024
    )

    observed = {
        "temperature": params.get("temperature"),
        "has_timeout": "timeout" in params,
    }

    problems = []
    if "expect_temperature" in case and observed["temperature"] != case["expect_temperature"]:
        problems.append(
            f"temperature {observed['temperature']!r}, expected {case['expect_temperature']!r}"
        )
    if case.get("expect_timeout") and not observed["has_timeout"]:
        problems.append("no request timeout")

    return {
        "provider": case["provider"],
        "model": case["model"],
        "temperature_in": case["temperature"],
        "observed": observed,
        "ok": not problems,
        "problems": problems,
    }


def conformance_matrix() -> dict[str, Any]:
    """Run every conformance check. No network access required."""
    checks = []
    for check in CONFORMANCE_CHECKS:
        cases = [_evaluate_case(case) for case in check["cases"]]
        checks.append(
            {
                "id": check["id"],
                "description": check["description"],
                "ok": all(case["ok"] for case in cases),
                "cases": cases,
            }
        )

    return {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
        "providers": sorted({case["provider"] for check in CONFORMANCE_CHECKS for case in check["cases"]}),
    }
