"""Tests for built-in tool safety and schemas."""

from pathlib import Path

import pytest

from magent.permissions import RiskTier, classify_file_op, classify_shell_command
from magent.tools import ToolExecutor


def test_file_read_outside_cwd_requires_confirmation(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    assert classify_file_op("read", str(outside), str(tmp_path)) == RiskTier.CONFIRM


@pytest.mark.asyncio
async def test_outline_file_reports_python_symbols(tmp_path: Path) -> None:
    source = tmp_path / "demo.py"
    source.write_text(
        "class Demo:\n"
        "    def method(self):\n"
        "        pass\n\n"
        "async def run():\n"
        "    pass\n",
        encoding="utf-8",
    )
    tools = ToolExecutor(str(tmp_path))

    result = await tools.outline_file("demo.py")

    assert result["ok"] is True
    names = {symbol["name"] for symbol in result["symbols"]}
    assert {"Demo", "method", "run"} <= names


def test_shell_control_is_blocked_even_if_allowlisted() -> None:
    assert classify_shell_command("git status; echo unsafe", ["git *"]) == RiskTier.BLOCK


def test_tool_definitions_have_required_arguments(tmp_path: Path) -> None:
    tools = ToolExecutor(str(tmp_path))
    defs = {d["function"]["name"]: d for d in tools.get_tool_definitions()}

    read_file_required = defs["read_file"]["function"]["parameters"]["required"]
    write_file_required = defs["write_file"]["function"]["parameters"]["required"]

    assert "path" in read_file_required
    assert {"path", "content"} <= set(write_file_required)
    assert "outline_file" in defs
    assert "read_file_range" in defs
