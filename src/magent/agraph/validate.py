"""MagAgent API around the AGS 1.0 reference validator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from magent.agraph import _reference_validator as reference
from magent.agraph.document import GraphDocument, GraphDocumentError, load_graph


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    pointer: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    document: GraphDocument | None
    findings: tuple[Finding, ...]

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "graph_id": self.document.graph_id if self.document else "",
            "graph_digest": self.document.digest if self.document else "",
            "findings": [item.as_dict() for item in self.findings],
        }


def validate_graph(source: str | Path | dict[str, Any] | GraphDocument, *, strict: bool = False) -> ValidationReport:
    try:
        document = source if isinstance(source, GraphDocument) else load_graph(source)
    except GraphDocumentError as exc:
        message = str(exc)
        code = "AG005" if "AG005" in message else "AG001"
        return ValidationReport(None, (Finding(code, "error", message),))
    raw = reference.Report(document.path or Path("<memory>"))
    reference.Validator(document.data, raw).run()
    findings = [Finding(item.code, item.severity, item.message, item.pointer) for item in raw.findings]
    required = int(document.data.get("requires_conformance", 1) or 1)
    if required > 3:
        findings.append(Finding("AG303", "error", f"graph requires unsupported conformance level {required}"))
    if strict:
        findings = [
            Finding(item.code, "error" if item.severity == "warning" else item.severity, item.message, item.pointer)
            for item in findings
        ]
    return ValidationReport(document, tuple(findings))
