"""Portable AGS run record construction and validation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ags
import jsonschema

from magent import __version__
from magent.agraph.constants import CONFORMANCE_LEVEL, SUPPORTED_FEATURES
from magent.agraph.document import GraphDocument

_AGS_ROOT = Path(ags.__file__).resolve().parent
RUN_SCHEMA = _AGS_ROOT / "schema" / "agentic-graph-run-1.0.schema.json"
if not RUN_SCHEMA.exists():
    RUN_SCHEMA = _AGS_ROOT.parent / "schema" / "agentic-graph-run-1.0.schema.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_run_record(document: GraphDocument, run_id: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "ags_version": "1.0",
        "kind": "AgenticGraphRun",
        "run_id": run_id,
        "graph_id": document.graph_id,
        "graph_version": str(document.data.get("version", "")),
        "graph_digest": document.digest,
        "harness": {
            "name": "MagAgent",
            "version": __version__,
            "conformance_level": CONFORMANCE_LEVEL,
            "supported_features": list(SUPPORTED_FEATURES),
        },
        "status": "running",
        "started_at": now_iso(),
        "params": params,
        "context": document.data.get("context") or {},
        "outputs": {},
        "usage": {
            "node_executions": 0,
            "tool_calls": 0,
            "wall_clock_seconds": 0.0,
            "cost_usd": 0.0,
        },
        "diagnostics": [],
        "nodes": [],
        "edges_taken": [],
        "metadata": {},
    }


def validate_run_record(record: dict[str, Any]) -> None:
    schema = json.loads(RUN_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        record
    )
