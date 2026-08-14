"""Safe OAP document parsing, validation, and serialization."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from magent.agent_profiles.errors import ProfileValidationError


class _ProfileLoader(yaml.SafeLoader):
    pass


# YAML 1.1 timestamps become datetime objects and break canonical JSON.
for _key, _rules in list(_ProfileLoader.yaml_implicit_resolvers.items()):
    _ProfileLoader.yaml_implicit_resolvers[_key] = [
        rule for rule in _rules if rule[0] != "tag:yaml.org,2002:timestamp"
    ]


SCHEMA_PATH = Path(__file__).parent / "schema" / "v1" / "profile.schema.json"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}, text
    raw = "\n".join(lines[1:end])
    data = yaml.load(raw, Loader=_ProfileLoader) or {}
    if not isinstance(data, dict):
        raise ProfileValidationError("frontmatter must be an object")
    return data, "\n".join(lines[end + 1 :]).strip()


def parse_document(path: Path) -> tuple[dict[str, Any], str, str]:
    text = path.read_text(encoding="utf-8", errors="strict")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        data, encoding, body = json.loads(text), "json", ""
    elif text.startswith("---"):
        data, body = split_frontmatter(text)
        encoding = "md"
    else:
        data, encoding, body = yaml.load(text, Loader=_ProfileLoader), "yaml", ""
    if not isinstance(data, dict):
        raise ProfileValidationError("profile document must be an object")
    if "oap" in data and body:
        role = data.setdefault("spec", {}).setdefault("role", {})
        role.setdefault("instructions", body)
    return data, body, encoding


def validate_document(document: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(part) for part in error.path)
        raise ProfileValidationError(f"{pointer or '/'}: {error.message}")
    for item in document.get("spec", {}).get("context", {}).get("files", []):
        if not isinstance(item, dict) or not str(item.get("path", "")).strip():
            raise ProfileValidationError("/spec/context/files: every entry requires path")


def render_document(document: dict[str, Any], encoding: str = "yaml") -> str:
    if encoding == "json":
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if encoding == "md":
        data = json.loads(json.dumps(document))
        instructions = str(data.get("spec", {}).get("role", {}).pop("instructions", ""))
        return "---\n" + yaml.safe_dump(data, sort_keys=False).rstrip() + "\n---\n\n" + instructions.strip() + "\n"
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
