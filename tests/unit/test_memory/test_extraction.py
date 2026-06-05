"""Tests for the memory extraction parser."""

from magent.memory.extraction import parse_extraction_response


class TestParseExtractionResponse:
    def test_valid_json_array(self):
        raw = '[{"id": "prefers_typescript", "type": "preference", "body": "# TypeScript\\nUser prefers TypeScript.", "links": []}]'
        result = parse_extraction_response(raw)
        assert len(result) == 1
        assert result[0]["id"] == "prefers_typescript"
        assert result[0]["type"] == "preference"

    def test_strips_markdown_fences(self):
        raw = '```json\n[{"id": "test_node", "type": "fact", "body": "A fact.", "links": []}]\n```'
        result = parse_extraction_response(raw)
        assert len(result) == 1

    def test_empty_array(self):
        result = parse_extraction_response("[]")
        assert result == []

    def test_invalid_json_returns_empty(self):
        result = parse_extraction_response("this is not json")
        assert result == []

    def test_filters_items_without_id(self):
        raw = '[{"type": "fact", "body": "no id"}, {"id": "valid_node", "type": "fact", "body": "has id", "links": []}]'
        result = parse_extraction_response(raw)
        assert len(result) == 1
        assert result[0]["id"] == "valid_node"

    def test_non_list_response_returns_empty(self):
        raw = '{"id": "single_obj", "type": "fact"}'
        result = parse_extraction_response(raw)
        assert result == []
