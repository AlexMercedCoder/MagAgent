"""Intelligence-tier routing with refusal-before-spending semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magent.agraph.mappings import TIER_TO_MODEL_ROLE
from magent.model_capabilities import model_capabilities


class RoutingError(ValueError):
    code = "RT011"


@dataclass(frozen=True)
class Route:
    requested_tier: str
    effective_tier: str
    role: str
    provider: str
    model: str
    downgraded: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_tier": self.requested_tier,
            "effective_tier": self.effective_tier,
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "downgraded": self.downgraded,
            "reason": self.reason,
        }


def route_for_node(config: Any, node: dict[str, Any]) -> Route:
    intelligence = node.get("intelligence") or {}
    tier = str(intelligence.get("tier", "standard"))
    role = TIER_TO_MODEL_ROLE.get(tier, "coding")
    roles = getattr(config, "model_roles", {})
    if role == "frontier" and role not in roles:
        role = "review"
    provider, model = config.provider_and_model_for_role(role)
    minimum = int(intelligence.get("min_context_tokens", 0) or 0)
    caps = model_capabilities(provider, model, config.provider_config(provider))
    available = int(caps.get("context_tokens", 0) or 0)
    if minimum and (not available or available < minimum):
        if not bool(intelligence.get("allow_downgrade", False)):
            raise RoutingError(
                f"RT011 route for {tier} requires {minimum} context tokens; {provider}/{model} advertises {available or 'unknown'}"
            )
        return Route(tier, tier, role, provider, model, True, "context requirement not verified")
    return Route(tier, tier, role, provider, model)
