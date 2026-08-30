"""Versioned, conflict-safe OAP authoring APIs for desktop clients."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent.agent_profiles.authoring import normalize_profile_name, profile_path
from magent.agent_profiles.composition import resolve_composition
from magent.agent_profiles.digest import digest_document, digest_spec
from magent.agent_profiles.documents import (
    SCHEMA_PATH,
    atomic_write,
    parse_document,
    render_document,
    validate_document,
)
from magent.agent_profiles.models import ResolvedProfile
from magent.agent_profiles.registry import AgentProfileRegistry

PROFILE_CONTRACT = "magent.oap-profile.v1"
UI_ANNOTATION_PREFIX = "dev.magcommandcenter."


def profile_contract(project: str | Path = ".", config: Any | None = None) -> dict[str, Any]:
    """Return the schema and local choices needed by a profile editor."""
    from magent.provider_catalog import PROVIDER_CATALOG
    from magent.skills import SkillRegistry
    from magent.tool_packs import list_packs
    from magent.tools.catalog import built_in_tool_definitions

    skills = SkillRegistry()
    skills.load()
    mcp = _configured_mcp(config)
    registry = AgentProfileRegistry(project, config)
    profiles, warnings = registry.discover()
    tools = [
        {
            "name": str(item.get("function", {}).get("name", "")),
            "description": str(item.get("function", {}).get("description", "")),
        }
        for item in built_in_tool_definitions()
        if item.get("function", {}).get("name")
    ]
    return {
        "ok": True,
        "contract": PROFILE_CONTRACT,
        "schema": json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
        "choices": {
            "scopes": ["user", "universal", "project", "portable"],
            "permission_modes": ["paranoid", "balanced", "silent", "yolo"],
            "network_modes": ["none", "ask", "read", "full"],
            "memory_modes": ["off", "read", "write", "read_write"],
            "writeback_modes": ["off", "propose", "auto"],
            "tools": tools,
            "tool_packs": list_packs(),
            "skills": skills.list_all(),
            "mcp_servers": sorted(mcp),
            "profiles": [
                profiles[name].as_dict(include_document=False) for name in sorted(profiles)
            ],
            "providers": [
                {
                    "id": name,
                    "label": str(spec.get("display") or spec.get("label") or name),
                    "default_model": str(spec.get("default_model") or ""),
                    "access_mode": str(spec.get("access_mode") or "api"),
                }
                for name, spec in PROVIDER_CATALOG.items()
            ],
        },
        "templates": _templates(),
        "guidance": {
            "profile_boundary": "An OAP profile controls agent behavior and narrows authority. It is not a user account, project, credential store, or filesystem sandbox.",
            "network": {
                "none": "No web or network tools are available.",
                "read": "Allow web search, research, page fetch, and browser inspection without arbitrary HTTP writes.",
                "full": "Allow read tools plus arbitrary HTTP methods. Use only when API writes are required.",
            },
            "effective_policy": "The active harness, enabled tool packs, inherited profiles, and parent agents may narrow these requests further.",
        },
        "warnings": warnings,
    }


def preview_profile(
    document: dict[str, Any], *, project: str | Path = ".", config: Any | None = None
) -> dict[str, Any]:
    """Validate a document and show its inheritance-aware effective authority."""
    from magent.agent_profiles.effective import resolve_effective_profile
    from magent.tools.catalog import built_in_tool_definitions

    candidate = _canonical_candidate(document)
    validate_document(candidate)
    name = normalize_profile_name(str(candidate.get("metadata", {}).get("name", "")))
    candidate["metadata"]["name"] = name
    registry = AgentProfileRegistry(project, config)
    profiles, discovery_warnings = registry.discover()
    resolved = ResolvedProfile(
        document=candidate,
        source_path=None,
        trust="preview",
        spec_digest=digest_spec(candidate),
        profile_digest=digest_document(candidate),
        encoding="md",
    )
    profiles[name] = resolved
    composed = resolve_composition(profiles)[name]
    dependencies = _dependencies(composed, profiles, config)
    result: dict[str, Any] = {
        "ok": True,
        "ready": dependencies["ok"],
        "contract": PROFILE_CONTRACT,
        "profile": composed.as_dict(),
        "dependencies": dependencies,
        "warnings": [*discovery_warnings, *composed.warnings],
    }
    if config is not None:
        granted = {
            str(item.get("function", {}).get("name", ""))
            for item in built_in_tool_definitions()
            if item.get("function", {}).get("name")
        }
        result["effective_profile"] = resolve_effective_profile(composed, config, granted).as_dict()
    return result


def apply_profile(
    document: dict[str, Any],
    *,
    scope: str,
    project: str | Path = ".",
    config: Any | None = None,
    expected_digest: str = "",
) -> dict[str, Any]:
    """Create or update one profile with optimistic concurrency."""
    preview = preview_profile(document, project=project, config=config)
    if not preview["ok"]:
        return preview
    candidate = _canonical_candidate(document)
    name = normalize_profile_name(str(candidate["metadata"]["name"]))
    target = profile_path(name, scope=scope, project=project)
    operation = "create"
    if target.exists():
        from magent.agent_profiles.delta import create_checkpoint

        current_document, _body, current_encoding = parse_document(target)
        current_digest = digest_document(current_document)
        if not expected_digest:
            return {
                "ok": False,
                "contract": PROFILE_CONTRACT,
                "conflict": True,
                "error": "Updating a profile requires its current profile_digest.",
                "current_digest": current_digest,
            }
        if expected_digest != current_digest:
            return {
                "ok": False,
                "contract": PROFILE_CONTRACT,
                "conflict": True,
                "error": "Profile changed since it was opened.",
                "expected_digest": expected_digest,
                "current_digest": current_digest,
            }
        current_revision = int(current_document.get("metadata", {}).get("revision", 1))
        checkpoint = create_checkpoint(target, current_document, current_encoding)
        candidate["metadata"]["revision"] = current_revision + 1
        candidate["state"] = copy.deepcopy(current_document.get("state", {}))
        candidate["history"] = copy.deepcopy(current_document.get("history", []))
        candidate["history"].append(
            {
                "revision": current_revision + 1,
                "at": datetime.now(UTC).isoformat(),
                "by": "magagent-desktop",
                "change": f"Profile edit; checkpoint {checkpoint.name}",
                "sections": ["metadata", "spec"],
            }
        )
        operation = "update"
    else:
        candidate["metadata"]["revision"] = 1
    validate_document(candidate)
    atomic_write(target, render_document(candidate, "md"))
    saved = AgentProfileRegistry(project, config).load_path(target)
    return {
        "ok": True,
        "contract": PROFILE_CONTRACT,
        "operation": operation,
        "scope": scope,
        "path": str(target),
        "profile": saved.as_dict(),
    }


def _canonical_candidate(document: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(document)
    candidate.pop("proposals", None)
    spec = candidate.setdefault("spec", {})
    if lifecycle := candidate.pop("lifecycle", None):
        spec["lifecycle"] = lifecycle
    tools = spec.get("tools") or {}
    if isinstance(tools.get("skills"), list):
        tools["skills"] = [
            item if isinstance(item, dict) else {"name": item} for item in tools["skills"]
        ]
    state = candidate.get("state")
    if isinstance(state, list):
        candidate["state"] = {
            "facts": [
                {
                    "id": str(item.get("id", "fact")),
                    "text": str(item.get("text", item.get("content", item.get("value", "")))),
                }
                for item in state
                if isinstance(item, dict)
            ]
        }
    return candidate


def profile_checkpoints(
    name: str, *, project: str | Path = ".", config: Any | None = None
) -> dict[str, Any]:
    """List validated rollback checkpoints for one writable profile."""
    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": f"Agent profile not found: {name}",
        }
    if resolved.source_path is None:
        return {"ok": True, "contract": PROFILE_CONTRACT, "profile": name, "checkpoints": []}
    path = resolved.source_path
    directory = (
        path.parent.parent / "profile-checkpoints"
        if path.parent.name == "agents"
        else path.parent / ".profile-checkpoints"
    )
    checkpoints = []
    for candidate in sorted(directory.glob(f"{resolved.name}-r*-*{path.suffix}.bak"), reverse=True):
        try:
            document, _body, _encoding = parse_document(candidate)
            checkpoints.append(
                {
                    "path": str(candidate),
                    "revision": int(document.get("metadata", {}).get("revision", 1)),
                    "profile_digest": digest_document(document),
                    "modified_at": candidate.stat().st_mtime,
                }
            )
        except Exception:
            continue
    return {
        "ok": True,
        "contract": PROFILE_CONTRACT,
        "profile": resolved.name,
        "checkpoints": checkpoints,
    }


def inspect_profile(
    name: str, *, project: str | Path = ".", config: Any | None = None
) -> dict[str, Any]:
    """Return document, effective authority, and revisions in one desktop round trip."""
    from magent.agent_profiles.effective import resolve_effective_profile
    from magent.tools.catalog import built_in_tool_definitions

    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": f"Agent profile not found: {name}",
        }
    granted = {
        str(item.get("function", {}).get("name", "")) for item in built_in_tool_definitions()
    }
    effective = resolve_effective_profile(resolved, config, granted).as_dict() if config else None
    return {
        "ok": True,
        "contract": PROFILE_CONTRACT,
        "profile": resolved.as_dict(),
        "effective_profile": effective,
        "checkpoints": profile_checkpoints(name, project=project, config=config)["checkpoints"],
    }


def rollback_profile(
    name: str,
    checkpoint: str | Path,
    *,
    project: str | Path = ".",
    config: Any | None = None,
    expected_digest: str,
) -> dict[str, Any]:
    """Restore a listed checkpoint after an optimistic-concurrency check."""
    from magent.agent_profiles.delta import restore_checkpoint

    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None or resolved.source_path is None:
        return {"ok": False, "contract": PROFILE_CONTRACT, "error": "Writable profile not found."}
    if not expected_digest or expected_digest != resolved.profile_digest:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "conflict": True,
            "error": "Profile changed or no profile_digest was supplied.",
            "current_digest": resolved.profile_digest,
        }
    allowed = {
        item["path"]
        for item in profile_checkpoints(name, project=project, config=config)["checkpoints"]
    }
    target = str(Path(checkpoint).expanduser().resolve())
    if target not in allowed:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": "Checkpoint is not part of this profile's revision history.",
        }
    return {"contract": PROFILE_CONTRACT, **restore_checkpoint(resolved.source_path, Path(target))}


def clone_profile(
    source: str,
    name: str,
    *,
    scope: str,
    project: str | Path = ".",
    config: Any | None = None,
) -> dict[str, Any]:
    registry = AgentProfileRegistry(project, config)
    resolved = registry.get(source)
    if resolved is None:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": f"Agent profile not found: {source}",
        }
    document = copy.deepcopy(resolved.document)
    document["metadata"]["name"] = normalize_profile_name(name)
    document["metadata"]["revision"] = 1
    document["metadata"]["description"] = f"Copy of {resolved.name}: " + str(
        document["metadata"].get("description", "")
    )
    document["state"] = []
    document["history"] = []
    document["proposals"] = []
    return apply_profile(document, scope=scope, project=project, config=config)


def import_profile(
    source: str | Path,
    *,
    scope: str,
    project: str | Path = ".",
    config: Any | None = None,
    name: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    path = Path(source).expanduser().resolve()
    document, _body, _encoding = parse_document(path)
    if name:
        document.setdefault("metadata", {})["name"] = normalize_profile_name(name)
    preview = preview_profile(document, project=project, config=config)
    if dry_run or not preview["ok"]:
        return {**preview, "source": str(path), "dry_run": dry_run}
    return apply_profile(document, scope=scope, project=project, config=config)


def export_profile(
    name: str, destination: str | Path, *, project: str | Path = ".", config: Any | None = None
) -> dict[str, Any]:
    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": f"Agent profile not found: {name}",
        }
    target = Path(destination).expanduser().resolve()
    document = _without_secret_like_fields(copy.deepcopy(resolved.document))
    atomic_write(target, render_document(document, "md"))
    return {
        "ok": True,
        "contract": PROFILE_CONTRACT,
        "profile": resolved.name,
        "path": str(target),
        "secrets_included": False,
    }


def delete_profile(
    name: str,
    *,
    project: str | Path = ".",
    config: Any | None = None,
    expected_digest: str,
) -> dict[str, Any]:
    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": f"Agent profile not found: {name}",
        }
    if resolved.source_path is None:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": "Managed profiles cannot be deleted.",
        }
    if not expected_digest or expected_digest != resolved.profile_digest:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "conflict": True,
            "error": "Profile changed or no profile_digest was supplied.",
            "current_digest": resolved.profile_digest,
        }
    resolved.source_path.unlink()
    return {
        "ok": True,
        "contract": PROFILE_CONTRACT,
        "profile": resolved.name,
        "deleted": str(resolved.source_path),
    }


def _configured_mcp(config: Any | None) -> dict[str, Any]:
    if config is None:
        return {}
    raw = getattr(config, "mcp_servers", {})
    if not isinstance(raw, dict):
        return {}
    servers = raw.get("servers", raw)
    return servers if isinstance(servers, dict) else {}


def _references(value: Any) -> set[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    return {
        str(item.get("name") if isinstance(item, dict) else item).strip()
        for item in value
        if str(item.get("name") if isinstance(item, dict) else item).strip()
    }


def _dependencies(
    profile: ResolvedProfile, profiles: dict[str, ResolvedProfile], config: Any | None
) -> dict[str, Any]:
    from magent.skills import SkillRegistry
    from magent.tools.catalog import built_in_tool_definitions

    documents = (*profile.lineage, profile.document)
    tool_names = {
        str(item.get("function", {}).get("name", "")) for item in built_in_tool_definitions()
    }
    skills = SkillRegistry()
    skills.load()
    skill_names = {str(item["name"]) for item in skills.list_all()}
    mcp_names = set(_configured_mcp(config))
    requested_tools: set[str] = set()
    requested_skills: set[str] = set()
    requested_mcp: set[str] = set()
    requested_subagents: set[str] = set()
    for document in documents:
        spec = document.get("spec", {})
        tools = spec.get("tools", {}) if isinstance(spec.get("tools"), dict) else {}
        requested_tools.update(str(item) for item in tools.get("allow", []) if str(item))
        requested_skills.update(_references(tools.get("skills")))
        requested_mcp.update(_references(tools.get("mcp_servers")))
        runtime = spec.get("runtime", {}) if isinstance(spec.get("runtime"), dict) else {}
        subagents = runtime.get("subagents")
        if isinstance(subagents, dict):
            subagents = subagents.get("allow", subagents.get("profiles", []))
        requested_subagents.update(_references(subagents))
    aliases = {"read", "write", "edit", "delete", "search", "shell", "web", "*"}
    missing_tools = sorted(
        name
        for name in requested_tools
        if name not in aliases and "*" not in name and name not in tool_names
    )
    missing = {
        "tools": missing_tools,
        "skills": sorted(requested_skills - skill_names),
        "mcp_servers": sorted(requested_mcp - mcp_names),
        "subagents": sorted(requested_subagents - set(profiles)),
    }
    return {
        "ok": not any(missing.values()),
        "requested": {
            "tools": sorted(requested_tools),
            "skills": sorted(requested_skills),
            "mcp_servers": sorted(requested_mcp),
            "subagents": sorted(requested_subagents),
        },
        "missing": missing,
    }


def _without_secret_like_fields(value: Any) -> Any:
    secret_words = ("api_key", "apikey", "token", "password", "secret", "private_key")
    if isinstance(value, dict):
        return {
            key: _without_secret_like_fields(item)
            for key, item in value.items()
            if not any(word in key.lower() for word in secret_words)
        }
    if isinstance(value, list):
        return [_without_secret_like_fields(item) for item in value]
    return value


def _templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "general",
            "title": "General assistant",
            "description": "Coding and productivity with balanced permissions.",
            "tools": ["*"],
            "network": "read",
        },
        {
            "id": "coder",
            "title": "Coding specialist",
            "description": "Inspect, edit, test, and review project code.",
            "tools": ["read", "write", "edit", "search", "shell"],
            "network": "read",
        },
        {
            "id": "researcher",
            "title": "Research specialist",
            "description": "Web research and source synthesis without project writes.",
            "tools": ["read", "web"],
            "network": "read",
        },
        {
            "id": "reviewer",
            "title": "Review specialist",
            "description": "Read-only code and documentation review.",
            "tools": ["read", "search"],
            "network": "none",
        },
        {
            "id": "custom",
            "title": "Custom",
            "description": "Start with explicit choices.",
            "tools": [],
            "network": "none",
        },
    ]
