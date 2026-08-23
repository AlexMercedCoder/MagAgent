"""In-process MagAgent chat runner used by the local Web UI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from magent.agent import AgentSession
from magent.agent_profiles.effective import resolve_effective_profile
from magent.agent_profiles.registry import AgentProfileRegistry
from magent.cli.command_context import build_extraction_provider, build_provider
from magent.config import load_config
from magent.tools.catalog import built_in_tool_definitions

ChunkCallback = Callable[[str, str], None]


class WebChatRunner:
    """Run bounded chat turns without shelling out to the CLI."""

    def __init__(self, username: str, project: str | Path):
        self.username = username
        self.project = str(Path(project).resolve())

    def _profile(self, name: str, config: Any):
        resolved = AgentProfileRegistry(self.project, config).get(name)
        if resolved is None:
            raise ValueError(f"Agent profile not found: {name}")
        granted = {
            str(item.get("function", {}).get("name", ""))
            for item in built_in_tool_definitions()
        }
        return resolve_effective_profile(resolved, config, granted)

    async def _single(
        self,
        prompt: str,
        *,
        history: list[dict[str, str]],
        profile_name: str = "",
        on_chunk: ChunkCallback | None = None,
    ) -> dict[str, Any]:
        config = load_config(self.username)
        profile = self._profile(profile_name, config) if profile_name else None
        provider = build_provider(
            config,
            profile.provider if profile else None,
            profile.model if profile else None,
        )
        session = AgentSession(
            username=self.username,
            config=config,
            provider=provider,
            extraction_provider=build_extraction_provider(config),
            cwd=self.project,
            interactive_permissions=False,
            profile=profile,
        )
        session.conversation = [
            {"role": item["role"], "content": item["content"]}
            for item in history[-40:]
            if item.get("role") in {"user", "assistant"}
        ]
        chunks: list[str] = []
        try:
            async for chunk in session.stream_chat(prompt):
                chunks.append(chunk)
                if on_chunk:
                    on_chunk(profile_name or "MagAgent", chunk)
            return {
                "content": "".join(chunks),
                "speaker": profile_name or "MagAgent",
                "session_id": session.session_id,
                "provider": provider.provider_id,
                "model": provider.model,
                "profile_revision": profile.resolved.revision if profile else None,
            }
        finally:
            await session.end_session()

    def run(
        self,
        conversation: dict[str, Any],
        prompt: str,
        *,
        on_chunk: ChunkCallback | None = None,
    ) -> list[dict[str, Any]]:
        history = [
            {"role": item.get("role", ""), "content": item.get("content", "")}
            for item in conversation.get("messages", [])
        ]

        async def execute() -> list[dict[str, Any]]:
            kind = conversation.get("kind", "chat")
            profiles = list(conversation.get("profiles") or [])
            if kind != "group":
                return [
                    await self._single(
                        prompt,
                        history=history,
                        profile_name=profiles[0] if profiles else "",
                        on_chunk=on_chunk,
                    )
                ]

            participant_results: list[dict[str, Any]] = []
            for profile in profiles:
                participant_prompt = (
                    f"You are @{profile} in a bounded group chat. Respond independently and concisely "
                    f"to the user's request. Do not attempt to invoke other agents.\n\n{prompt}"
                )
                participant_results.append(
                    await self._single(
                        participant_prompt,
                        history=history,
                        profile_name=profile,
                        on_chunk=on_chunk,
                    )
                )
            coordinator = str(conversation.get("coordinator") or profiles[0])
            evidence = "\n\n".join(
                f"@{item['speaker']}: {item['content']}" for item in participant_results
            )
            synthesis = await self._single(
                "As the group coordinator, synthesize the participant responses into one useful final "
                f"answer. Call out important disagreement; do not invent work.\n\nUser request:\n{prompt}"
                f"\n\nParticipant responses:\n{evidence}",
                history=history,
                profile_name=coordinator,
                on_chunk=on_chunk,
            )
            synthesis["speaker"] = f"{coordinator} · synthesis"
            return [*participant_results, synthesis]

        return asyncio.run(execute())
