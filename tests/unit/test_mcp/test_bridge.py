"""Tests for the SDK-independent side of the private MCP bridge protocol."""

from __future__ import annotations

from dataclasses import dataclass

from magent.mcp.bridge import (
    _bounded_resource_result,
    _catalog_meta,
    _dump,
    _error_text,
    _expand_mapping,
    _mode,
    _tool_catalog,
)


@dataclass
class _Dumpable:
    value: str

    def model_dump(self, **_: object) -> dict[str, str]:
        return {"value": self.value}


@dataclass
class _Tool:
    name: str
    description: str
    input_schema: dict[str, object]


def test_mode_maps_profile_values_to_sdk_modes() -> None:
    assert _mode("auto") == "auto"
    assert _mode("legacy") == "legacy"
    assert _mode("modern") == "2026-07-28"


def test_dump_recursively_normalizes_model_values() -> None:
    assert _dump({"items": [_Dumpable("ok")]}) == {"items": [{"value": "ok"}]}


def test_tool_catalog_uses_snake_case_sdk_schema() -> None:
    tool = _Tool("echo", "Echo input", {"type": "object"})
    assert _tool_catalog(type("Result", (), {"tools": [tool]})()) == [
        {
            "name": "echo",
            "description": "Echo input",
            "input_schema": {"type": "object"},
        }
    ]


def test_error_text_flattens_exception_groups() -> None:
    error = ExceptionGroup("outer", [ValueError("bad profile"), RuntimeError("closed")])
    assert _error_text(error) == "ExceptionGroup: ValueError: bad profile; RuntimeError: closed"


def test_expand_mapping_resolves_environment_inside_bridge(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TEST_TOKEN", "secret")
    assert _expand_mapping({"Authorization": "Bearer ${MCP_TEST_TOKEN}"}) == {
        "Authorization": "Bearer secret"
    }


def test_catalog_meta_and_resource_bounds() -> None:
    result = type(
        "Result",
        (),
        {
            "ttl_ms": 5000,
            "cache_scope": "public",
            "next_cursor": "next",
            "model_dump": lambda self, **kwargs: {
                "contents": [{"uri": "memory://large", "text": "x" * 200_001}]
            },
        },
    )()

    assert _catalog_meta(result)["ttl_ms"] == 5000
    bounded = _bounded_resource_result(result)
    assert bounded["truncated"] is True
    assert len(bounded["contents"][0]["text"]) == 200_000
