"""Portable Open Agent Profiles for the local Web UI.

`magent agent export` and `magent agent import` already move profiles between
workspaces, but both work on file paths. A browser has a download and an upload,
not a path, so these wrap the same machinery around in-memory documents.

The same rules apply as on the CLI: secret-like fields never leave, an imported
document is previewed before it is applied, and inbound runtime state is
dropped. A shared profile is a role to adopt, not a snapshot of someone else's
session, and learned state is untrusted context everywhere else in MagAgent; it
must not become trusted by travelling through a file.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from magent.agent_profiles.authoring import normalize_profile_name
from magent.agent_profiles.desktop import (
    PROFILE_CONTRACT,
    _without_secret_like_fields,
    apply_profile,
    preview_profile,
)
from magent.agent_profiles.registry import AgentProfileRegistry

# Runtime accretion, not identity. Never exported, never imported.
TRANSIENT_KEYS = ("state", "history", "inbox", "proposals")


def export_document(
    name: str, *, project: str | Path = ".", config: Any | None = None
) -> dict[str, Any]:
    """Return a profile as a portable document, without secrets or state."""
    resolved = AgentProfileRegistry(project, config).get(name)
    if resolved is None:
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": f"Agent profile not found: {name}",
        }

    document = _without_secret_like_fields(copy.deepcopy(resolved.document))
    for key in TRANSIENT_KEYS:
        document.pop(key, None)

    return {
        "ok": True,
        "contract": PROFILE_CONTRACT,
        "profile": resolved.name,
        "filename": f"{resolved.name}.agent.md",
        "document": document,
        "secrets_included": False,
    }


def import_document(
    document: Any,
    *,
    scope: str = "project",
    name: str = "",
    project: str | Path = ".",
    config: Any | None = None,
) -> dict[str, Any]:
    """Adopt a profile document supplied by the browser."""
    if not isinstance(document, dict):
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": "A profile document must be an object.",
        }

    incoming = copy.deepcopy(document)
    for key in TRANSIENT_KEYS:
        incoming.pop(key, None)

    metadata = dict(incoming.get("metadata") or {})
    if name:
        metadata["name"] = normalize_profile_name(name)
    if not metadata.get("name"):
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "error": "The profile document has no metadata.name.",
        }
    # An import starts this workspace's revision history rather than inheriting
    # a count from wherever the file came from.
    metadata["revision"] = 1
    incoming["metadata"] = metadata

    # A file chosen in a browser can be anything. Validation errors must come
    # back as a result the UI can show, not as an exception that 500s the
    # endpoint and tells the user nothing.
    try:
        preview = preview_profile(incoming, project=project, config=config)
    except Exception as error:  # noqa: BLE001 - surfaced to the client
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "imported": False,
            "error": f"That file is not a valid agent profile: {error}",
        }
    if not preview.get("ok"):
        return {**preview, "imported": False}

    try:
        applied = apply_profile(incoming, scope=scope, project=project, config=config)
    except Exception as error:  # noqa: BLE001 - surfaced to the client
        return {
            "ok": False,
            "contract": PROFILE_CONTRACT,
            "imported": False,
            "error": str(error),
        }
    if not applied.get("ok") and applied.get("conflict"):
        # apply_profile treats an existing name as an update and demands the
        # current digest. For an import that is really "this name is taken",
        # which is what the person needs to hear.
        return {
            **applied,
            "imported": False,
            "error": (
                f"A profile named {metadata['name']} already exists here. "
                "Rename it in the file's metadata.name, or delete the existing one first."
            ),
        }
    return {**applied, "imported": bool(applied.get("ok"))}
