"""Open Agent Profile (OAP) v1 support for MagAgent."""

from magent.agent_profiles.effective import resolve_effective_profile
from magent.agent_profiles.models import Adjustment, EffectiveProfile, ResolvedProfile
from magent.agent_profiles.registry import AgentProfileRegistry

__all__ = [
    "Adjustment",
    "AgentProfileRegistry",
    "EffectiveProfile",
    "ResolvedProfile",
    "resolve_effective_profile",
]
