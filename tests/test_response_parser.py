"""Tests for LLM response parser."""
from pr_reviewer.llm.response_parser import parse_file_analysis


def test_direct_json():
    result = parse_file_analysis(
        '{"summary": "Added X", "findings": [], '
        '"dependencies_impact": "none", "linter_correlation": "none"}'
    )
    assert result is not None
    assert result["summary"] == "Added X"


def test_markdown_fence():
    result = parse_file_analysis(
        '```json\n'
        '{"summary": "Changed Y", "findings": [{"severity": "high", "category": "logic_error", "title": "Bug"}], "dependencies_impact": "breaks", "linter_correlation": "none"}\n'
        '```'
    )
    assert result is not None
    assert result["summary"] == "Changed Y"
    assert len(result["findings"]) == 1


def test_empty():
    assert parse_file_analysis("") is None
    assert parse_file_analysis("   ") is None


def test_nonsense():
    assert parse_file_analysis("not json at all") is None
