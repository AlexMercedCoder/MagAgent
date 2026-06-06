"""Schema-limited conversational config proposals."""

from __future__ import annotations

import copy
import difflib
import re
from typing import Any

import tomli_w

from magent.config import load_global_config, load_user_profile
from magent.config_safety import backup_config
from magent.config_ux import (
    configure_memory,
    configure_subagents,
    set_default_provider,
    set_model_role,
)
from magent.events import record_event
from magent.permission_ux import permission_set
from magent.provider_catalog import PROVIDER_CATALOG, PROVIDER_ORDER

PROPOSAL_STORE = "config_proposals"


def propose_config_change(store: Any, text: str, username: str | None = None) -> dict[str, Any]:
    """Create a limited config proposal from natural language."""
    operations = _parse_operations(text)
    if not operations:
        return {"ok": False, "error": "No safe config changes recognized", "text": text}
    diff = _proposal_diff(operations, username)
    proposal = store.append(
        PROPOSAL_STORE,
        {
            "text": text,
            "operations": operations,
            "status": "pending",
            "diff": diff,
            "requires_typed_confirm": any(op.get("risk") == "high" for op in operations),
        },
    )
    record_event(store, "config.proposed", "Config proposal created", detail={"proposal_id": proposal["id"]})
    return {"ok": True, "proposal": proposal}


def list_config_proposals(store: Any, status: str = "pending") -> dict[str, Any]:
    proposals = list(reversed(store.read(PROPOSAL_STORE, [])))
    if status:
        proposals = [item for item in proposals if item.get("status") == status]
    return {"ok": True, "proposals": proposals}


def apply_config_proposal(store: Any, proposal_id: str, username: str | None = None) -> dict[str, Any]:
    proposals = store.read(PROPOSAL_STORE, [])
    proposal = next((item for item in proposals if item.get("id") == proposal_id), None)
    if not proposal:
        return {"ok": False, "error": f"Config proposal not found: {proposal_id}"}
    if proposal.get("status") != "pending":
        return {"ok": False, "error": f"Config proposal is {proposal.get('status')}"}
    backup = backup_config(username)
    results = [_apply_operation(op, username) for op in proposal.get("operations", [])]
    for item in proposals:
        if item.get("id") == proposal_id:
            item["status"] = "applied"
            item["backup_id"] = backup.get("backup_id")
            item["results"] = results
    store.write(PROPOSAL_STORE, proposals)
    record_event(
        store,
        "config.applied",
        "Config proposal applied",
        detail={"proposal_id": proposal_id, "backup_id": backup.get("backup_id"), "results": results},
    )
    return {"ok": all(result.get("ok") for result in results), "backup": backup, "results": results}


def discard_config_proposal(store: Any, proposal_id: str) -> dict[str, Any]:
    proposal = store.update_item(PROPOSAL_STORE, proposal_id, status="discarded")
    if not proposal:
        return {"ok": False, "error": f"Config proposal not found: {proposal_id}"}
    record_event(store, "config.discarded", "Config proposal discarded", detail={"proposal_id": proposal_id})
    return {"ok": True, "proposal": proposal}


def _parse_operations(text: str) -> list[dict[str, Any]]:
    normalized = text.lower()
    operations: list[dict[str, Any]] = []
    provider_ids = _mentioned_providers(normalized)
    if "default" in normalized and provider_ids:
        provider_id = provider_ids[0]
        operations.append(
            {
                "type": "default_provider",
                "provider": provider_id,
                "model": PROVIDER_CATALOG[provider_id]["default_model"],
            }
        )
    for role in ("coding", "review", "memory", "cheap"):
        if role in normalized and provider_ids:
            provider_id = provider_ids[0]
            if len(provider_ids) > 1:
                idx = min(len(provider_ids) - 1, ["coding", "review", "memory", "cheap"].index(role))
                provider_id = provider_ids[idx]
            operations.append(
                {
                    "type": "model_role",
                    "role": role,
                    "value": f"{provider_id}/{PROVIDER_CATALOG[provider_id]['default_model']}",
                }
            )
    for mode in ("inbox-first", "manual", "auto"):
        if mode in normalized:
            operations.append({"type": "memory", "mode": mode})
    subagent_match = re.search(r"(?:max|cap|limit)\D+(\d+)\D+sub", normalized)
    if subagent_match:
        operations.append({"type": "subagents", "max_subagents": int(subagent_match.group(1))})
    for mode in ("silent", "balanced", "paranoid", "yolo"):
        if mode in normalized:
            operations.append({"type": "permission", "mode": mode, "risk": "high" if mode == "yolo" else "normal"})
    return operations


def _mentioned_providers(text: str) -> list[str]:
    aliases = {"mistral ai": "mistral", "opencode go": "opencode-go", "opencode zen": "opencode-zen", "openai": "openai"}
    found = []
    for label, provider_id in aliases.items():
        if label in text and provider_id not in found:
            found.append(provider_id)
    for provider_id in PROVIDER_ORDER:
        if provider_id.replace("_", " ") in text and provider_id not in found:
            found.append(provider_id)
    return found


def _proposal_diff(operations: list[dict[str, Any]], username: str | None = None) -> dict[str, str]:
    global_before = load_global_config()
    user_before = load_user_profile(username) if username else {}
    global_after = copy.deepcopy(global_before)
    user_after = copy.deepcopy(user_before)
    for op in operations:
        if op["type"] == "default_provider":
            global_after.setdefault("defaults", {})["provider"] = op["provider"]
            global_after.setdefault("defaults", {})["model"] = op["model"]
        elif op["type"] == "model_role":
            global_after.setdefault("models", {})[op["role"]] = op["value"]
        elif op["type"] == "subagents":
            global_after.setdefault("subagents", {})["max_subagents"] = op["max_subagents"]
        elif op["type"] == "memory":
            user_after.setdefault("memory", {})["auto_write"] = op["mode"] == "auto"
            user_after.setdefault("memory", {})["inbox_first"] = op["mode"] == "inbox-first"
        elif op["type"] == "permission":
            user_after.setdefault("permissions", {})["mode"] = op["mode"]
    return {
        "global": _dict_diff(global_before, global_after, "global-before", "global-after"),
        "user": _dict_diff(user_before, user_after, "user-before", "user-after") if username else "",
    }


def _dict_diff(before: dict[str, Any], after: dict[str, Any], before_name: str, after_name: str) -> str:
    before_lines = tomli_w.dumps(before).splitlines(keepends=True)
    after_lines = tomli_w.dumps(after).splitlines(keepends=True)
    return "".join(difflib.unified_diff(before_lines, after_lines, fromfile=before_name, tofile=after_name))


def _apply_operation(op: dict[str, Any], username: str | None = None) -> dict[str, Any]:
    if op["type"] == "default_provider":
        return set_default_provider(op["provider"], op["model"])
    if op["type"] == "model_role":
        return set_model_role(op["role"], op["value"])
    if op["type"] == "memory" and username:
        return configure_memory(username, mode=op["mode"])
    if op["type"] == "subagents":
        return configure_subagents(max_subagents=op["max_subagents"])
    if op["type"] == "permission" and username:
        return permission_set(username, op["mode"])
    return {"ok": False, "error": f"Cannot apply operation: {op}"}
