"""Offline Open Agent Profile Level 3 harness conformance checks."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from magent.agent_profiles.digest import digest_document
from magent.agent_profiles.documents import (
    parse_document,
    render_document,
    validate_document,
)
from magent.agent_profiles.effective import resolve_effective_profile
from magent.agent_profiles.errors import ProfileError, ProfileValidationError
from magent.agent_profiles.registry import AgentProfileRegistry

FIXTURES = Path(__file__).parent / "schema" / "v1" / "conformance.json"


class _Policy:
    permission_mode = "balanced"
    default_provider = "test"
    default_model = "test-model"
    memory_budget_tokens = 4000
    memory_mode = "read_write"
    max_subagents = 3
    max_parallel_subagents = 2

    def get(self, *parts: str, default: Any = None) -> Any:
        values = {
            ("agent", "max_model_rounds_per_turn"): 16,
            ("agent_profiles", "max_state_tokens"): 1200,
            ("agent_profiles", "writeback"): "propose",
            ("agent_profiles", "max_delegation_depth"): 3,
            ("tool_budgets",): {},
            ("budgets", "session_usd"): 0.0,
        }
        return values.get(parts, default)


def run_conformance() -> dict[str, Any]:
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []

    def record(name: str, callback) -> None:
        try:
            detail = callback()
            checks.append({"name": name, "ok": True, "detail": detail or "passed"})
        except Exception as exc:
            checks.append({"name": name, "ok": False, "detail": str(exc)})

    def valid_documents() -> str:
        for document in fixtures["valid"]:
            validate_document(document)
        return f"{len(fixtures['valid'])} valid fixtures"

    def invalid_documents() -> str:
        rejected = 0
        for document in fixtures["invalid"]:
            try:
                validate_document(document)
            except ProfileValidationError:
                rejected += 1
        if rejected != len(fixtures["invalid"]):
            raise AssertionError("one or more invalid fixtures were accepted")
        return f"{rejected} invalid fixtures rejected"

    def encoding_parity() -> str:
        document = deepcopy(fixtures["valid"][0])
        instructions = document["spec"]["role"]["instructions"]
        document["spec"]["role"]["instructions"] = instructions.rstrip() + "\n"
        expected = digest_document(document)
        with tempfile.TemporaryDirectory() as directory:
            for encoding, suffix in (("yaml", ".yaml"), ("json", ".json"), ("md", ".md")):
                path = Path(directory) / f"profile{suffix}"
                path.write_text(render_document(document, encoding), encoding="utf-8")
                parsed, _body, _kind = parse_document(path)
                if digest_document(parsed) != expected:
                    raise AssertionError(f"canonical digest differs for {encoding}")
        return expected

    def inheritance_and_narrowing() -> str:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".magent" / "agents"
            root.mkdir(parents=True)
            for document in fixtures["valid"]:
                name = document["metadata"]["name"]
                (root / f"{name}.yaml").write_text(render_document(document), encoding="utf-8")
            registry = AgentProfileRegistry(directory, _Policy())
            child = registry.get("child")
            if child is None or len(child.lineage) != 1:
                raise AssertionError("extends did not resolve exactly one parent")
            effective = resolve_effective_profile(
                child, _Policy(), {"read_file", "write_file", "run_shell"}
            )
            if effective.tools != {"read_file"}:
                raise AssertionError("child widened inherited tool policy")
            if effective.mcp_servers != ("github",):
                raise AssertionError("MCP selection did not remain constrained")
            if effective.allows_memory("write"):
                raise AssertionError("memory store mode widened during inheritance")
        return "extends and capability intersection"

    def cycle_rejection() -> str:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".magent" / "agents"
            root.mkdir(parents=True)
            for name, parent in (("a", "b"), ("b", "a")):
                document = {
                    "oap": "1.0",
                    "extends": parent,
                    "metadata": {"name": name, "revision": 1},
                    "spec": {"role": {}},
                }
                (root / f"{name}.yaml").write_text(render_document(document), encoding="utf-8")
            try:
                AgentProfileRegistry(directory, _Policy()).discover()
            except ProfileError:
                return "cycle rejected"
        raise AssertionError("inheritance cycle was accepted")

    record("valid-documents", valid_documents)
    record("invalid-documents", invalid_documents)
    record("encoding-digest-parity", encoding_parity)
    record("inheritance-policy-narrowing", inheritance_and_narrowing)
    record("inheritance-cycle-rejection", cycle_rejection)
    return {
        "ok": all(item["ok"] for item in checks),
        "schema": "oap.harness-conformance.v1",
        "oap": "1.0",
        "level": 3,
        "checks": checks,
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
    }
