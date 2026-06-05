"""Memory extraction: LLM-powered post-task knowledge distillation."""

from __future__ import annotations

import json
import re
from typing import Any

EXTRACTION_SYSTEM_PROMPT = """You are a memory extraction assistant for an AI coding agent called MagAgent.

Your job is to analyze a conversation between a user and an AI agent, then identify and structure knowledge that should be stored in the agent's long-term memory graph.

The memory graph stores knowledge as typed nodes. Extract only meaningful, reusable knowledge — not trivial conversation details.

Node types available:
- preference: User preferences (coding style, tools, languages, frameworks they prefer/dislike)
- project: Project metadata (name, tech stack, key decisions, architecture patterns)
- pattern: Recurring code patterns, idioms, or anti-patterns the user cares about
- skill_learned: A technique or skill that was learned/applied during this session
- fact: General facts about the user, their environment, or their workflow
- session_summary: Brief summary of what was accomplished this session
- error_pattern: A recurring error and its solution
- contact: A person, team, or external service mentioned
- bookmark: A URL found to be useful, with tags for future retrieval

Output ONLY a JSON array of memory nodes. Each node must have:
{
  "id": "snake_case_id_no_spaces",
  "type": "one_of_the_types_above",
  "body": "# Node Title\n\nMarkdown body with details. Use [[other_node_id]] wikilinks to link related nodes.",
  "links": ["other_node_id"],  // explicit edge list (can also use wikilinks in body)
  "url": "https://...",        // bookmark nodes only
  "tags": ["tag1", "tag2"]     // bookmark nodes only
}

Rules:
- IDs must be unique snake_case, max 60 chars
- Only output nodes for genuinely useful, reusable knowledge
- Do NOT include trivial conversation details
- For project-specific nodes, include the project name in the ID (e.g., project_myapp)
- session_summary should always be included if significant work was done
- Output ONLY valid JSON array, no other text
"""


def build_extraction_prompt(conversation_turns: list[dict[str, str]]) -> str:
    """Build the user message for the extraction call."""
    lines = ["Analyze this conversation and extract memory nodes:\n"]
    for turn in conversation_turns[-20:]:  # last 20 turns max
        role = turn.get("role", "user")
        content = turn.get("content", "")[:1000]  # truncate long turns
        lines.append(f"[{role.upper()}]: {content}\n")
    return "\n".join(lines)


def parse_extraction_response(response: str) -> list[dict[str, Any]]:
    """Parse LLM extraction response into list of node dicts."""
    # Strip markdown code fences if present
    response = response.strip()
    response = re.sub(r"^```(?:json)?\n?", "", response)
    response = re.sub(r"\n?```$", "", response)
    response = response.strip()

    try:
        parsed = json.loads(response)
        if not isinstance(parsed, list):
            return []
        # Validate each node minimally
        valid = []
        for item in parsed:
            if isinstance(item, dict) and item.get("id") and item.get("type"):
                valid.append(item)
        return valid
    except json.JSONDecodeError:
        return []


async def extract_memories(
    conversation_turns: list[dict[str, str]],
    provider_fn: Any,  # async callable(messages) -> str
) -> list[dict[str, Any]]:
    """
    Run memory extraction using a provider function.

    provider_fn: async function that takes a list of messages and returns the LLM response string.
    """
    if not conversation_turns:
        return []

    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": build_extraction_prompt(conversation_turns)},
    ]

    try:
        response = await provider_fn(messages)
        return parse_extraction_response(response)
    except Exception:
        return []
