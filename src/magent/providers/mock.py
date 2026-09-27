"""Offline ``mock`` provider for first-run demos, tests and CI.

It never touches the network and needs no key. Replies are deterministic: the
same messages always produce the same text. Every reply starts with a label so
nobody mistakes it for a model answer.

The provider is wired into LiteLLM as a custom handler, so it flows through the
same code paths as a real provider: streaming, the tool loop, usage logging and
memory extraction. It never requests tools, so a mock run cannot change files.

Use it with ``magent ask "hello" --provider mock`` or select it as the default
with ``magent provider set mock``.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

PROVIDER_ID = "mock"
LITELLM_PREFIX = "magent-mock"
DEFAULT_MODEL = "offline-demo"
REPLY_LABEL = "[MagAgent mock provider: offline demo reply, no model was called]"

_registered = False


def litellm_model(model: str) -> str:
    name = model or DEFAULT_MODEL
    return name if name.startswith(f"{LITELLM_PREFIX}/") else f"{LITELLM_PREFIX}/{name}"


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        ).strip()
    return str(content or "")


def _recalled_node_ids(messages: list[dict[str, Any]]) -> list[str]:
    for message in messages:
        if message.get("role") != "system":
            continue
        match = re.search(r"^- Anchors: (.+)$", _text(message.get("content")), re.MULTILINE)
        if match:
            return re.findall(r"`([^`]+)`", match.group(1))
    return []


def mock_reply(messages: list[dict[str, Any]]) -> str:
    """Deterministic reply for a message list."""

    system = " ".join(_text(m.get("content")) for m in messages if m.get("role") == "system")
    if "memory extraction assistant" in system:
        # Memory extraction expects a JSON array. A mock run writes no memories.
        return "[]"
    user_turns = [_text(m.get("content")) for m in messages if m.get("role") == "user"]
    last = " ".join((user_turns[-1] if user_turns else "").split())
    preview = last if len(last) <= 200 else last[:199].rstrip() + "…"
    digest = hashlib.sha256(last.encode("utf-8")).hexdigest()[:8]
    recalled = _recalled_node_ids(messages)
    memory_line = (
        f"Memory recalled for this turn: {', '.join(recalled)}."
        if recalled
        else "No stored memory matched this message."
    )
    return "\n\n".join(
        [
            REPLY_LABEL,
            f'You said: "{preview}" (message {digest}).',
            memory_line,
            "MagAgent is installed and working. For real answers, add a provider key, "
            "for example: `magent auth add nous-portal --api-key-stdin`, then "
            "`magent provider set nous-portal`.",
        ]
    )


def _usage(messages: list[dict[str, Any]], reply: str) -> dict[str, int]:
    prompt_chars = sum(len(_text(m.get("content"))) for m in messages)
    prompt_tokens = max(1, prompt_chars // 4)
    completion_tokens = max(1, len(reply) // 4)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _model_response(model: str, messages: list[dict[str, Any]]) -> Any:
    from litellm.types.utils import Choices, Message, ModelResponse, Usage

    reply = mock_reply(messages)
    return ModelResponse(
        id="chatcmpl-magent-mock-" + hashlib.sha256(reply.encode("utf-8")).hexdigest()[:12],
        created=int(time.time()),
        model=model,
        object="chat.completion",
        choices=[
            Choices(
                index=0,
                finish_reason="stop",
                message=Message(role="assistant", content=reply),
            )
        ],
        usage=Usage(**_usage(messages, reply)),
    )


def _chunks(messages: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    reply = mock_reply(messages)
    words = reply.split(" ")
    for index, word in enumerate(words):
        yield {
            "text": word if index == len(words) - 1 else word + " ",
            "is_finished": False,
            "finish_reason": None,
            "usage": None,
            "index": 0,
            "tool_use": None,
        }
    yield {
        "text": "",
        "is_finished": True,
        "finish_reason": "stop",
        "usage": _usage(messages, reply),
        "index": 0,
        "tool_use": None,
    }


def ensure_registered() -> None:
    """Register the handler with LiteLLM once per process."""

    global _registered
    if _registered:
        return
    import litellm
    from litellm import CustomLLM

    class MagentMockLLM(CustomLLM):
        def completion(self, *args: Any, **kwargs: Any) -> Any:
            return _model_response(str(kwargs.get("model", "")), list(kwargs.get("messages", [])))

        async def acompletion(self, *args: Any, **kwargs: Any) -> Any:
            return self.completion(*args, **kwargs)

        def streaming(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
            yield from _chunks(list(kwargs.get("messages", [])))

        async def astreaming(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            for chunk in _chunks(list(kwargs.get("messages", []))):
                yield chunk

    existing = [
        item
        for item in (getattr(litellm, "custom_provider_map", None) or [])
        if item.get("provider") != LITELLM_PREFIX
    ]
    litellm.custom_provider_map = [
        *existing,
        {"provider": LITELLM_PREFIX, "custom_handler": MagentMockLLM()},
    ]
    _registered = True
