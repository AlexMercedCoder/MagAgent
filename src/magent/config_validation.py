"""Config validation and ambient instruction loading."""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

from magent.config import Config, load_config, load_global_config
from magent.config_ux import MODEL_ROLES
from magent.provider_catalog import PROVIDER_CATALOG


def validate_config(username: str | None = None, cwd: str | Path = ".") -> dict[str, Any]:
    config = load_config(username)
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if config.default_provider not in PROVIDER_CATALOG and config.default_provider not in config.providers:
        issues.append({"path": "defaults.provider", "message": f"unknown provider {config.default_provider}"})
    if not config.default_model:
        issues.append({"path": "defaults.model", "message": "default model is empty"})

    for role, value in config.model_roles.items():
        if role not in MODEL_ROLES:
            warnings.append({"path": f"models.{role}", "message": "unknown model role"})
        values = value if isinstance(value, list) else ([value] if value else [])
        for item in values:
            if "/" not in str(item):
                warnings.append({"path": f"models.{role}", "message": "use provider/model format for explicit routing"})
                continue
            provider_id = str(item).split("/", 1)[0]
            if provider_id not in PROVIDER_CATALOG and provider_id not in config.providers:
                issues.append({"path": f"models.{role}", "message": f"unknown provider {provider_id}"})

    for source in config.instruction_sources:
        matches = _expand_instruction_source(source, cwd)
        if not matches and not str(source).startswith(("http://", "https://")):
            warnings.append({"path": "instructions", "message": f"instruction source not found: {source}"})

    return {"ok": not issues, "issues": issues, "warnings": warnings}


def config_schema() -> dict[str, Any]:
    cfg = load_global_config()
    fields: list[dict[str, str]] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(f"{prefix}.{key}" if prefix else key, child)
            return
        fields.append({"path": prefix, "type": type(value).__name__, "default": repr(value)})

    walk("", cfg)
    fields.append({"path": "instructions[]", "type": "str", "default": "[]"})
    return {"ok": True, "fields": fields}


def load_ambient_instructions(config: Config, cwd: str | Path, *, max_chars: int = 12000) -> str:
    blocks: list[str] = []
    used = 0
    for source in config.instruction_sources:
        for path in _expand_instruction_source(source, cwd):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            remaining = max_chars - used
            if remaining <= 0:
                break
            excerpt = text[:remaining]
            used += len(excerpt)
            blocks.append(f"### {path.relative_to(Path(cwd).resolve()) if _is_relative_to(path, Path(cwd).resolve()) else path}\n\n{excerpt}")
        if used >= max_chars:
            break
    if not blocks:
        return ""
    return "## Ambient Project Instructions\n\n" + "\n\n".join(blocks)


def _expand_instruction_source(source: str, cwd: str | Path) -> list[Path]:
    source = str(source).strip()
    if not source or source.startswith(("http://", "https://")):
        return []
    root = Path(cwd).resolve()
    expanded = Path(source).expanduser()
    pattern = str(expanded if expanded.is_absolute() else root / expanded)
    return [Path(item).resolve() for item in glob.glob(pattern) if Path(item).is_file()]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
