"""Validated Open Agent Profile authoring and default selection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from magent import config as magent_config
from magent.agent_profiles.documents import atomic_write, render_document, validate_document
from magent.agent_profiles.registry import AgentProfileRegistry

PROFILE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
DEFAULT_PROFILE = "magagent"


def normalize_profile_name(name: str) -> str:
    value = name.strip().lower().replace(" ", "-")
    if not PROFILE_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "Profile names must start with a letter or number and contain only "
            "lowercase letters, numbers, dots, underscores, or hyphens."
        )
    return value


def build_profile_document(
    *,
    name: str,
    description: str,
    role: dict[str, Any],
    model: dict[str, Any] | None = None,
    tools: dict[str, Any] | None = None,
    permissions: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
    extends: list[str] | None = None,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate a complete OAP v1 document."""
    normalized = normalize_profile_name(name)
    spec: dict[str, Any] = {"role": _without_empty(role)}
    for key, value in (
        ("model", model),
        ("tools", tools),
        ("permissions", permissions),
        ("runtime", runtime),
        ("memory", memory),
        ("context", context),
    ):
        cleaned = _without_empty(value or {})
        if cleaned:
            spec[key] = cleaned
    document: dict[str, Any] = {
        "oap": "1.0",
        "metadata": {
            "name": normalized,
            "description": description.strip() or normalized,
            "revision": 1,
            **({"annotations": _without_empty(annotations or {})} if _without_empty(annotations or {}) else {}),
        },
        "spec": spec,
        "state": [],
        "history": [],
        "proposals": [],
        "lifecycle": _without_empty(lifecycle or {"writeback": "propose"}),
    }
    inherited = [normalize_profile_name(item) for item in (extends or []) if item.strip()]
    if inherited:
        document["extends"] = inherited[0] if len(inherited) == 1 else inherited
    validate_document(document)
    return document


def profile_path(name: str, *, scope: str, project: str | Path = ".") -> Path:
    normalized = normalize_profile_name(name)
    if scope == "user":
        root = magent_config.CONFIG_DIR / "agents"
    elif scope == "project":
        root = Path(project).expanduser().resolve() / ".magent" / "agents"
    elif scope == "portable":
        root = Path(project).expanduser().resolve() / ".agents"
    else:
        raise ValueError("Profile scope must be user, project, or portable.")
    return root / f"{normalized}.md"


def write_profile(
    document: dict[str, Any],
    *,
    scope: str,
    project: str | Path = ".",
    overwrite: bool = False,
) -> dict[str, Any]:
    validate_document(document)
    name = str(document.get("metadata", {}).get("name") or "")
    target = profile_path(name, scope=scope, project=project)
    if target.exists() and not overwrite:
        return {"ok": False, "error": f"Profile already exists: {target}", "path": str(target)}
    atomic_write(target, render_document(document, "md"))
    return {"ok": True, "name": name, "scope": scope, "path": str(target)}


def default_profile_status(username: str | None, project: str | Path = ".") -> dict[str, Any]:
    config = magent_config.load_config(username)
    name = config.default_agent_profile or DEFAULT_PROFILE
    resolved = AgentProfileRegistry(project, config).get(name)
    return {
        "ok": resolved is not None,
        "profile": name,
        "resolved": resolved.as_dict(include_document=False) if resolved else None,
        "fallback": DEFAULT_PROFILE if resolved is None else "",
    }


def set_default_profile(
    name: str,
    *,
    username: str | None,
    project: str | Path = ".",
    global_scope: bool = False,
) -> dict[str, Any]:
    normalized = normalize_profile_name(name)
    config = magent_config.load_config(username)
    resolved = AgentProfileRegistry(project, config).get(normalized)
    if resolved is None:
        return {"ok": False, "error": f"Agent profile not found: {normalized}"}
    if global_scope:
        data = magent_config.load_global_config()
        data.setdefault("agent_profiles", {})["default_profile"] = normalized
        magent_config.save_global_config(data)
        scope = "global"
    else:
        if not username:
            return {"ok": False, "error": "An active user is required for a user default."}
        data = magent_config.load_user_profile(username)
        data.setdefault("preferences", {})["default_agent_profile"] = normalized
        magent_config.save_user_profile(username, data)
        scope = "user"
    return {"ok": True, "profile": normalized, "scope": scope}


def clear_default_profile(*, username: str | None, global_scope: bool = False) -> dict[str, Any]:
    if global_scope:
        data = magent_config.load_global_config()
        data.setdefault("agent_profiles", {})["default_profile"] = DEFAULT_PROFILE
        magent_config.save_global_config(data)
        scope = "global"
    else:
        if not username:
            return {"ok": False, "error": "An active user is required for a user default."}
        data = magent_config.load_user_profile(username)
        data.setdefault("preferences", {}).pop("default_agent_profile", None)
        magent_config.save_user_profile(username, data)
        scope = "user"
    return {"ok": True, "profile": DEFAULT_PROFILE, "scope": scope}


def _without_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != "" and item != [] and item != {}
    }
