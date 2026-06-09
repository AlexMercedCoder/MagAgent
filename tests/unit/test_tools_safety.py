"""Tests for built-in tool safety and schemas."""

import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import magent.tools as tools_module
import magent.tools.executor as executor_module
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


def test_shell_control_read_only_chains_do_not_prompt_spam() -> None:
    assert classify_shell_command("cat file.html 2>&1 | wc -l") == RiskTier.SILENT
    assert classify_shell_command("wc -l file.html 2>/dev/null; echo ---; tail -5 file.html") == RiskTier.SILENT
    assert classify_shell_command("pip list 2>/dev/null | grep -iE 'docx|pptx|python'") == RiskTier.SILENT
    assert classify_shell_command('cd /tmp && python3 -c "import docx; print(docx.__version__)"') == RiskTier.SILENT
    assert classify_shell_command("curl -s 'https://example.com' | head -500") == RiskTier.AUTO
    assert (
        classify_shell_command(
            "curl -s 'https://example.com' | grep -i 'primary\\|color\\|font' | head -100"
        )
        == RiskTier.AUTO
    )


def test_network_fetch_mutation_or_download_still_requires_confirmation() -> None:
    assert classify_shell_command("curl -X POST https://example.com") == RiskTier.CONFIRM
    assert classify_shell_command("curl -s https://example.com -o page.html") == RiskTier.CONFIRM
    assert classify_shell_command("wget https://example.com -O page.html") == RiskTier.CONFIRM


def test_macos_shell_rewrites_prefer_python3(monkeypatch) -> None:
    monkeypatch.setattr(executor_module.sys, "platform", "darwin")

    assert (
        executor_module._prefer_platform_python_command("pip install python-pptx")
        == "python3 -m pip install python-pptx"
    )
    assert (
        executor_module._prefer_platform_python_command("pip list | grep docx")
        == "python3 -m pip list | grep docx"
    )
    assert executor_module._prefer_platform_python_command("python -c 'print(1)'") == "python3 -c 'print(1)'"


def test_shell_control_blocks_dangerous_segment_even_if_allowlisted() -> None:
    assert classify_shell_command("git status; rm -rf build", ["git *"]) == RiskTier.BLOCK


@pytest.mark.asyncio
async def test_noninteractive_permissions_return_structured_denial(tmp_path: Path) -> None:
    tools = ToolExecutor(
        str(tmp_path),
        permission_mode="balanced",
        interactive_permissions=False,
    )

    result = await tools.run_shell("git status; rm -rf build")

    assert result["ok"] is False
    assert result["permission_required"] is True
    assert result["permission_reason"] == "permission-required"


@pytest.mark.asyncio
async def test_web_search_prefers_relevant_ddgs_results(monkeypatch, tmp_path: Path) -> None:
    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def text(self, query: str, max_results: int = 8):
            return [
                {
                    "title": "complete - German translation",
                    "body": "Dictionary entry for complete.",
                    "href": "https://dict.example/complete",
                },
                {
                    "title": "A History of Cheese",
                    "body": "Cheese making has ancient origins and a long timeline.",
                    "href": "https://example.com/history-of-cheese",
                },
                {
                    "title": "The History of Cheese: From Ancient Origins to Modern Day",
                    "body": "Short social video caption.",
                    "href": "https://www.tiktok.com/@example/video/123",
                },
            ]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))
    tools = ToolExecutor(str(tmp_path), permission_mode="silent")

    result = await tools.web_search("Complete history of cheese from ancient origins", max_results=8)

    assert result["ok"] is True
    assert result["source"] == "ddgs"
    assert result["filtered_count"] == 2
    assert [item["url"] for item in result["results"]] == ["https://example.com/history-of-cheese"]


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
async def test_dispatch_normalizes_common_write_file_aliases(tmp_path: Path) -> None:
    tools = ToolExecutor(str(tmp_path), permission_mode="silent")

    result = await tools.dispatch(
        "write_file",
        {"file_path": "notes/alias.txt", "contents": "alias worked"},
    )

    assert result["ok"] is True
    assert (tmp_path / "notes" / "alias.txt").read_text(encoding="utf-8") == "alias worked"


@pytest.mark.asyncio
async def test_shell_control_can_be_session_allowed(tmp_path: Path) -> None:
    tools = ToolExecutor(
        str(tmp_path),
        permission_mode="balanced",
        trusted_shell_patterns=["cat a.txt | wc -l"],
    )
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")

    result = await tools.run_shell("cat a.txt | wc -l")

    assert result["ok"] is True
    assert result["stdout"].strip() == "2"


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
