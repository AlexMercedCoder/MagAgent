from __future__ import annotations

import pytest

from magent.agent import _coerce_mcp_form_value
from magent.tools import ToolExecutor


def test_mcp_form_values_are_coerced_without_model_inference():
    assert _coerce_mcp_form_value("42", "integer") == 42
    assert _coerce_mcp_form_value("yes", "boolean") is True
    assert _coerce_mcp_form_value("a, b", "array") == ["a", "b"]
    with pytest.raises(ValueError):
        _coerce_mcp_form_value("maybe", "boolean")


def test_selective_tools_keeps_default_set_smaller(tmp_path):
    executor = ToolExecutor(cwd=str(tmp_path), username="alice")
    all_tools = executor.get_tool_definitions()
    selected = executor.get_tool_definitions_for_message("read the config and fix the failing test")

    assert len(selected) < len(all_tools)
    names = {item["function"]["name"] for item in selected}
    assert {"read_file", "edit_file", "run_shell", "search_codebase"} <= names


def test_selective_tools_adds_web_and_database_tools(tmp_path):
    executor = ToolExecutor(cwd=str(tmp_path), username="alice")
    selected = executor.get_tool_definitions_for_message(
        "check the latest API docs and query the sqlite database"
    )
    names = {item["function"]["name"] for item in selected}

    assert "web_search" in names
    assert "http_request" in names
    assert "db_query" in names


def test_selective_tools_keeps_graph_output_emission_available(tmp_path):
    executor = ToolExecutor(cwd=str(tmp_path), username="alice")
    selected = executor.get_tool_definitions_for_message(
        "Declared outputs: findings. Call graph_emit_output(name, value)."
    )

    assert "graph_emit_output" in {item["function"]["name"] for item in selected}
    assert "graph_emit_output" in {
        item["function"]["name"] for item in executor.get_tool_definitions()
    }


def test_coordination_pack_exposes_profile_and_session_tools(tmp_path):
    executor = ToolExecutor(cwd=str(tmp_path), username="alice")
    names = {item["function"]["name"] for item in executor.get_tool_definitions()}

    assert {"create_agent_profile", "list_sessions", "send_session_message"} <= names


def test_selective_tools_adds_document_artifact_tools(tmp_path):
    executor = ToolExecutor(cwd=str(tmp_path), username="alice")
    selected = executor.get_tool_definitions_for_message(
        "make a PowerPoint presentation and Word document from this research"
    )
    names = {item["function"]["name"] for item in selected}

    assert "create_docx" in names
    assert "create_pptx" in names


def test_selective_tools_adds_visual_artifact_tools(tmp_path):
    executor = ToolExecutor(cwd=str(tmp_path), username="alice")
    selected = executor.get_tool_definitions_for_message(
        "create a mermaid diagram, svg logo, and png image for this workflow"
    )
    names = {item["function"]["name"] for item in selected}

    assert "create_diagram" in names
    assert "create_svg" in names
    assert "create_image" in names


def test_tool_budget_truncates_large_output(tmp_path):
    executor = ToolExecutor(cwd=str(tmp_path), username="alice", tool_budgets={"read_file": 10})
    result = executor._budget_result("read_file", {"ok": True, "content": "x" * 50})

    assert result["budgeted"] is True
    assert "truncated" in result["content"]
