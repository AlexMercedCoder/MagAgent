"""G-5: offline mock provider."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from magent.provider_catalog import PROVIDER_ORDER, provider_metadata, validate_provider_catalog
from magent.providers import build_provider
from magent.providers.mock import REPLY_LABEL, mock_reply


def test_mock_is_a_local_catalog_provider_needing_no_key() -> None:
    assert "mock" in PROVIDER_ORDER
    metadata = provider_metadata("mock")
    assert metadata["local"] is True and metadata["offline"] is True
    assert "env" not in metadata
    assert validate_provider_catalog()["ok"] is True


def test_mock_replies_are_deterministic_and_labeled() -> None:
    messages = [{"role": "user", "content": "hello there"}]
    first, second = mock_reply(messages), mock_reply(list(messages))
    assert first == second
    assert first.startswith(REPLY_LABEL)
    assert '"hello there"' in first
    assert mock_reply([{"role": "user", "content": "other"}]) != first


def test_mock_reports_recalled_memory_anchors() -> None:
    messages = [
        {
            "role": "system",
            "content": "# MagAgent Memory Recall\n\n- Anchors: `prefers_pytest`, `proj`\n",
        },
        {"role": "user", "content": "what do I like?"},
    ]
    assert "Memory recalled for this turn: prefers_pytest, proj." in mock_reply(messages)


def test_mock_memory_extraction_writes_nothing() -> None:
    from magent.memory.extraction import EXTRACTION_SYSTEM_PROMPT

    reply = mock_reply(
        [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": "x"},
        ]
    )
    assert json.loads(reply) == []


def test_mock_provider_completes_and_streams_offline(monkeypatch) -> None:
    import litellm

    def no_network(*_args, **_kwargs):  # pragma: no cover - failure path
        raise AssertionError("mock provider must not reach the network")

    monkeypatch.setattr("httpx.AsyncClient.send", no_network)
    provider = build_provider("mock", "offline-demo", None, {})
    messages = [{"role": "user", "content": "ping"}]

    async def run() -> tuple[str, list[str], object]:
        text = await provider.complete(messages)
        chunks = [chunk async for chunk in provider.stream(messages)]
        raw = await litellm.acompletion(messages=messages, **provider.request_kwargs())
        return text, chunks, raw

    text, chunks, raw = asyncio.run(run())
    assert text == mock_reply(messages)
    assert "".join(chunks) == text
    assert raw.usage.total_tokens > 0
    assert provider.display_name == "Mock (offline demo) / offline-demo"


def test_ask_with_mock_provider_runs_end_to_end(monkeypatch, tmp_path: Path) -> None:
    from magent.cli import main as cli_main
    from tests.unit.test_cli import redirect_config

    redirect_config(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "demo"]).exit_code == 0
    assert (
        runner.invoke(
            cli_main.app, ["config", "set", "memory.extraction_provider", "mock"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(cli_main.app, ["config", "set", "memory.semantic_enabled", "false"]).exit_code
        == 0
    )

    result = runner.invoke(
        cli_main.app,
        ["ask", "hello offline", "--provider", "mock", "--project", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["response"].startswith(REPLY_LABEL)
    assert payload["memory_evidence"][0]["schema"] == "magent.memory-evidence.v1"


def test_naming_only_a_provider_uses_that_providers_default_model() -> None:
    from magent.cli.command_context import build_provider as cli_build_provider
    from magent.config import Config

    config = Config({"defaults": {"provider": "ollama", "model": "qwen2.5-coder:32b"}}, {})
    assert cli_build_provider(config, "mock", None).model == "offline-demo"
    assert cli_build_provider(config, "mock", "custom-name").model == "custom-name"
    assert cli_build_provider(config, None, None).model == "qwen2.5-coder:32b"


def test_scripted_mode_plays_tool_calls_then_content(tmp_path: Path, monkeypatch) -> None:
    from magent.providers.mock import scripted_step

    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            {
                "scripts": [
                    {"when": "special", "steps": [{"tool": "read_file", "arguments": {"path": "a"}}]}
                ],
                "default": [{"content": "plain"}],
            }
        )
    )
    monkeypatch.setenv("MAGENT_MOCK_SCRIPT", str(script))
    first = [{"role": "user", "content": "a special request"}]
    assert scripted_step(first) == {"tool": "read_file", "arguments": {"path": "a"}}
    after_tool = [*first, {"role": "assistant", "content": None}, {"role": "tool", "content": "x"}]
    assert "Script finished" in scripted_step(after_tool)["content"]
    assert scripted_step([{"role": "user", "content": "other"}]) == {"content": "plain"}

    provider = build_provider("mock", "offline-demo", None, {})

    async def run() -> object:
        import litellm

        return await litellm.acompletion(messages=first, **provider.request_kwargs())

    response = asyncio.run(run())
    call = response.choices[0].message.tool_calls[0]
    assert call.function.name == "read_file" and json.loads(call.function.arguments) == {"path": "a"}


def test_scripted_mode_reports_an_unreadable_script(monkeypatch, tmp_path: Path) -> None:
    from magent.providers.mock import scripted_step

    monkeypatch.setenv("MAGENT_MOCK_SCRIPT", str(tmp_path / "missing.json"))
    assert "Could not read" in scripted_step([{"role": "user", "content": "x"}])["content"]
