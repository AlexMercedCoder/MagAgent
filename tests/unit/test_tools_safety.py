"""Tests for built-in tool safety and schemas."""

import zipfile
from pathlib import Path

import pytest

import magent.tools as tools_module
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


@pytest.mark.asyncio
async def test_noninteractive_permissions_return_structured_denial(tmp_path: Path) -> None:
    tools = ToolExecutor(
        str(tmp_path),
        permission_mode="balanced",
        interactive_permissions=False,
    )

    result = await tools.run_shell("git status; echo unsafe")

    assert result["ok"] is False
    assert result["permission_required"] is True
    assert result["permission_reason"] == "permission-required"


def test_tool_definitions_have_required_arguments(tmp_path: Path) -> None:
    tools = ToolExecutor(str(tmp_path))
    defs = {d["function"]["name"]: d for d in tools.get_tool_definitions()}

    read_file_required = defs["read_file"]["function"]["parameters"]["required"]
    write_file_required = defs["write_file"]["function"]["parameters"]["required"]

    assert "path" in read_file_required
    assert {"path", "content"} <= set(write_file_required)
    assert "outline_file" in defs
    assert "read_file_range" in defs
    assert "deep_research" in defs


@pytest.mark.asyncio
async def test_file_tools_read_write_edit_list_diff_and_range(tmp_path: Path) -> None:
    tools = ToolExecutor(str(tmp_path), permission_mode="silent")

    written = await tools.write_file("notes/a.txt", "one\ntwo\nthree\n")
    read = await tools.read_file("notes/a.txt")
    ranged = await tools.read_file_range("notes/a.txt", 2, 3)
    edited = await tools.edit_file("notes/a.txt", "two", "TWO")
    (tmp_path / "notes" / "b.txt").write_text("one\nTWO\nfour\n", encoding="utf-8")
    diff = await tools.diff_files("notes/a.txt", "notes/b.txt")
    listed = await tools.list_dir("notes")

    assert written["ok"] is True
    assert read["lines"] == 3
    assert "2: two" in ranged["content"]
    assert edited["ok"] is True
    assert diff["changed"] is True
    assert {entry["name"] for entry in listed["entries"]} == {"a.txt", "b.txt"}


@pytest.mark.asyncio
async def test_deep_research_collects_sources(monkeypatch, tmp_path: Path) -> None:
    tools = ToolExecutor(str(tmp_path), permission_mode="silent")

    async def fake_search(query: str, max_results: int = 8):
        return {
            "ok": True,
            "query": query,
            "results": [
                {
                    "title": "Example research",
                    "snippet": "Useful source snippet",
                    "url": "https://example.com/research",
                }
            ],
        }

    async def fake_fetch(url: str, extract_article: bool = True):
        return {
            "ok": True,
            "url": url,
            "status": 200,
            "content": "Long article text about the research topic.",
            "extractor": "test",
        }

    monkeypatch.setattr(tools, "web_search", fake_search)
    monkeypatch.setattr(tools, "web_fetch", fake_fetch)

    result = await tools.deep_research("agent UX", questions=["desktop apps"], max_sources=2)

    assert result["ok"] is True
    assert result["source_count"] == 1
    assert result["sources"][0]["url"] == "https://example.com/research"
    assert "Research summary" in result["summary"]


@pytest.mark.asyncio
async def test_archive_tools_roundtrip_zip(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.txt").write_text("hello", encoding="utf-8")
    tools = ToolExecutor(str(tmp_path), permission_mode="silent")

    compressed = await tools.compress("src", "archive.zip", format="zip")
    extracted = await tools.extract("archive.zip", "out")

    assert compressed["ok"] is True
    assert zipfile.is_zipfile(tmp_path / "archive.zip")
    assert extracted["ok"] is True
    assert (tmp_path / "out" / "src" / "demo.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_run_shell_run_python_and_search_codebase(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("needle = 'found'\n", encoding="utf-8")
    tools = ToolExecutor(str(tmp_path), permission_mode="silent")
    calls = []

    class FakeProc:
        returncode = 0

        async def communicate(self):
            if calls[-1][0] == "rg":
                return (f"{tmp_path}/app.py:1:needle = 'found'\n".encode(), b"")
            return (b"hello\n", b"")

        def kill(self):
            return None

    async def fake_create_subprocess_exec(*argv, **kwargs):
        calls.append(argv)
        return FakeProc()

    monkeypatch.setattr(
        tools_module.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(tools_module.shutil, "which", lambda name: "/usr/bin/rg" if name == "rg" else None)

    shell = await tools.run_shell("echo hello")
    python = await tools.run_python("print('hello from python')")
    search = await tools.search_codebase("needle")

    assert shell["ok"] is True
    assert shell["stdout"].strip() == "hello"
    assert python["ok"] is True
    assert python["stdout"].strip() == "hello"
    assert search["ok"] is True
    assert search["total"] >= 1


@pytest.mark.asyncio
async def test_json_query_and_docs_search(tmp_path: Path) -> None:
    (tmp_path / "data.json").write_text('{"items": [{"name": "Ada"}]}', encoding="utf-8")
    tools = ToolExecutor(str(tmp_path), permission_mode="silent")

    query = await tools.json_query("data.json", "items[0].name")
    docs = await tools.magent_docs_search("semantic memory", limit=2)

    assert query == {"ok": True, "result": "Ada"}
    assert docs["ok"] is True
    assert docs["results"]
