"""Expected artifact inference and verification helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ARTIFACT_RE = re.compile(
    r"(?<![\w./-])([A-Za-z0-9][A-Za-z0-9_.-]{0,120}\."
    r"(?:html|css|js|ts|tsx|jsx|py|md|txt|json|toml|yaml|yml|docx|pptx|pdf|svg|png|jpg|jpeg|mmd))"
    r"(?![\w/-])",
    re.IGNORECASE,
)

MIN_ARTIFACT_BYTES = {
    ".html": 80,
    ".svg": 80,
    ".docx": 200,
    ".pptx": 200,
    ".pdf": 200,
    ".png": 100,
    ".jpg": 100,
    ".jpeg": 100,
}


def infer_expected_artifacts(message: str, *, cwd: str | Path = ".") -> list[str]:
    """Infer likely requested artifact paths from a user prompt."""
    root = Path(cwd).resolve()
    paths: list[str] = []
    for match in ARTIFACT_RE.finditer(message or ""):
        raw = match.group(1).strip(" .,'\"`")
        if not raw or raw.lower().startswith(("http.", "www.")):
            continue
        candidate = Path(raw).expanduser()
        resolved = candidate if candidate.is_absolute() else root / candidate
        resolved = resolved.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        value = str(resolved)
        if value not in paths:
            paths.append(value)
    return paths


def verify_expected_artifacts(paths: list[str]) -> dict[str, Any]:
    """Return missing or placeholder-like expected artifacts."""
    findings = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            findings.append({"path": str(path), "ok": False, "reason": "missing"})
            continue
        if path.is_dir():
            findings.append({"path": str(path), "ok": True, "reason": "directory"})
            continue
        size = path.stat().st_size
        suffix = path.suffix.lower()
        if suffix in {".html", ".svg", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text.lower() in {path.name.lower(), path.stem.lower()}:
                findings.append(
                    {"path": str(path), "ok": False, "reason": "placeholder content", "bytes": size}
                )
                continue
        minimum = MIN_ARTIFACT_BYTES.get(suffix, 1)
        if size < minimum:
            findings.append(
                {
                    "path": str(path),
                    "ok": False,
                    "reason": f"too small ({size} bytes)",
                    "bytes": size,
                }
            )
            continue
        findings.append({"path": str(path), "ok": True, "reason": "exists", "bytes": size})
    failed = [item for item in findings if not item.get("ok")]
    return {"ok": not failed, "artifacts": findings, "failed": failed}


def artifact_audit_note(audit: dict[str, Any]) -> str:
    """Render unresolved artifact findings for final assistant responses."""
    failed = audit.get("failed") or []
    if not failed:
        return ""
    lines = ["", "Artifact verification:", "Some requested artifacts are unresolved:"]
    for item in failed:
        lines.append(f"- `{item.get('path')}`: {item.get('reason')}")
    return "\n".join(lines)
