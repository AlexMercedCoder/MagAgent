"""Review-first, model-assisted Open Agent Profile authoring."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from magent.agent_profiles.authoring import build_profile_document
from magent.agent_profiles.desktop import apply_profile, preview_profile, profile_contract
from magent.agent_profiles.documents import atomic_write

GENERATION_CONTRACT = "magent.oap-profile-generation.v1"


def _json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found")
    value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("response root is not an object")
    return value


def _baseline(prompt: str, name: str = "") -> dict[str, Any]:
    words = re.findall(r"[a-z0-9]+", name.lower() or prompt.lower())
    slug = "-".join(words[:6])[:63].strip("-") or "generated-specialist"
    return build_profile_document(
        name=slug,
        description=f"Use for work matching: {prompt.strip()[:420]}",
        role={
            "instructions": (
                f"You are a specialist for this purpose: {prompt.strip()}\n\n"
                "Work within the active harness policy, verify consequential results, and "
                "report uncertainty clearly."
            ),
            "objectives": [prompt.strip()[:500]],
            "constraints": ["Never widen authority beyond the active harness or parent agent."],
        },
        permissions={"default": "ask", "shell": "ask", "edit": "ask", "network": "ask"},
        lifecycle={"writeback": "propose"},
        annotations={"oap.dev/generated": "true"},
    )


async def generate_profile_proposal(
    prompt: str,
    *,
    project: str | Path = ".",
    config: Any,
    name: str = "",
    extends: str = "",
    autonomous: bool = False,
    provider: Any | None = None,
) -> dict[str, Any]:
    """Generate a strictly validated OAP proposal without persisting a profile."""
    request = prompt.strip()
    if not request:
        return {
            "ok": False,
            "contract": GENERATION_CONTRACT,
            "error": "Describe the profile to generate.",
        }
    if provider is None:
        from magent.cli.command_context import build_provider_for_role

        provider = build_provider_for_role(config, "review")
    contract = profile_contract(project, config)
    baseline = _baseline(request, name)
    if extends:
        baseline["extends"] = [{"name": extends.strip().lstrip("@")}]
    prompt_digest = "sha256:" + hashlib.sha256(request.encode("utf-8")).hexdigest()
    payload = {
        "request": request,
        "baseline": baseline,
        "schema": contract["schema"],
        "available": contract["choices"],
        "rules": [
            "Return exactly one complete OAP AgentProfile JSON object and no markdown.",
            "Use only available providers, tools, skills, MCP servers, and base profiles.",
            "Never invent commands, hooks, packages, credentials, environment values, or state facts.",
            "Use ask or deny for consequential permissions unless the request explicitly requires narrower access.",
            "Set lifecycle.writeback to propose. The profile can narrow authority but never widen harness policy.",
        ],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are the OAP profile-authoring specialist. Produce conservative, portable, "
                "schema-valid profile data. A generated document is a proposal, not authority."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    findings: list[str] = []
    for _attempt in range(3):
        raw = await provider.complete(messages, temperature=0.1, max_tokens=10000)
        try:
            document = _json_object(raw)
            metadata = document.setdefault("metadata", {})
            metadata.pop("trust", None)
            metadata["revision"] = 1
            if name:
                metadata["name"] = name.strip().lower().replace(" ", "-")
            document["state"] = {}
            document["history"] = []
            document.setdefault("spec", {}).setdefault("lifecycle", {})["writeback"] = "propose"
            preview = preview_profile(document, project=project, config=config)
            if not preview.get("ready", True):
                missing = preview.get("dependencies", {}).get("missing") or []
                raise ValueError("unresolved local references: " + ", ".join(map(str, missing)))
        except Exception as exc:  # noqa: BLE001 - model output is untrusted input
            findings.append(str(exc))
            messages.extend(
                (
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "Repair the complete profile and return JSON only. Validation finding: "
                            + str(exc)
                        ),
                    },
                )
            )
            continue
        return {
            **preview,
            "ok": True,
            "contract": GENERATION_CONTRACT,
            "proposal": True,
            "autonomous": autonomous,
            "requires_review": autonomous,
            "document": document,
            "rationale": {
                "request": request,
                "safety": "Generated authority remains subject to OAP validation and local policy narrowing.",
            },
            "warnings": list(preview.get("warnings") or []),
            "unresolved_references": [],
            "model": getattr(provider, "display_name", "planning model"),
            "prompt_digest": prompt_digest,
        }
    return {
        "ok": False,
        "contract": GENERATION_CONTRACT,
        "error": "The model could not produce a valid OAP profile after three attempts.",
        "findings": findings,
        "prompt_digest": prompt_digest,
    }


def store_profile_proposal(
    proposal: dict[str, Any], *, project: str | Path = ".", reason: str = "agent-suggested"
) -> dict[str, Any]:
    """Persist a non-authoritative proposal for later review."""
    proposal_id = str(uuid.uuid4())
    root = Path(project).expanduser().resolve() / ".magent" / "profile-proposals"
    target = root / f"{proposal_id}.json"
    payload = {**proposal, "proposal_id": proposal_id, "status": "pending", "reason": reason}
    atomic_write(target, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return {**payload, "path": str(target)}


def accept_generated_profile(
    proposal: dict[str, Any],
    *,
    scope: str,
    project: str | Path,
    config: Any,
) -> dict[str, Any]:
    """Persist a previously reviewed generated document through the normal OAP boundary."""
    document = proposal.get("document")
    if not isinstance(document, dict):
        return {
            "ok": False,
            "contract": GENERATION_CONTRACT,
            "error": "Proposal has no profile document.",
        }
    return apply_profile(document, scope=scope, project=project, config=config)
