"""Resolve OAP ``extends`` chains without flattening away security constraints."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from magent.agent_profiles.digest import digest_document
from magent.agent_profiles.errors import ProfileError
from magent.agent_profiles.models import ResolvedProfile


def extension_names(document: dict[str, Any]) -> tuple[str, ...]:
    raw = document.get("extends", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ProfileError("profile extends must be a name or an array of names")
    names = tuple(str(item).strip().lstrip("@").lower() for item in raw if str(item).strip())
    if len(names) != len(set(names)):
        raise ProfileError("profile extends contains duplicate parent names")
    return names


def resolve_composition(
    profiles: dict[str, ResolvedProfile],
) -> dict[str, ResolvedProfile]:
    """Attach parent documents in oldest-first order and reject invalid graphs."""
    resolved: dict[str, ResolvedProfile] = {}
    visiting: list[str] = []

    def visit(name: str) -> ResolvedProfile:
        if name in resolved:
            return resolved[name]
        if name in visiting:
            cycle = " -> ".join([*visiting[visiting.index(name) :], name])
            raise ProfileError(f"profile inheritance cycle: {cycle}")
        profile = profiles.get(name)
        if profile is None:
            raise ProfileError(f"extended profile not found: {name}")
        visiting.append(name)
        lineage: list[dict[str, Any]] = []
        warnings = list(profile.warnings)
        for parent_name in extension_names(profile.document):
            parent = visit(parent_name)
            for document in (*parent.lineage, parent.document):
                parent_id = str(document.get("metadata", {}).get("name", ""))
                if parent_id and all(
                    str(item.get("metadata", {}).get("name", "")) != parent_id for item in lineage
                ):
                    lineage.append(document)
            warnings.append(f"extends {parent.name}@r{parent.revision}")
        visiting.pop()
        resolved[name] = replace(
            profile,
            lineage=tuple(lineage),
            warnings=tuple(dict.fromkeys(warnings)),
            resolution_digest=digest_document(
                {
                    "lineage": lineage,
                    "profile": profile.document,
                }
            ),
        )
        return resolved[name]

    for profile_name in sorted(profiles):
        visit(profile_name)
    return resolved
