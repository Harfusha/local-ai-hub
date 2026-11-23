import pytest
from src.local_ai_hub.laya_test_suggester import LayaTestSuggester


def test_test_suggester_int_division():
    suggester = LayaTestSuggester()

    code = """
def divide_items(total: int, count: int) -> float:
    return total / count
"""
    suggestion = suggester.analyze_function(code)

    assert suggestion.target_function == "divide_items"
    assert "ZeroDivisionError" in suggestion.potential_exceptions
    # Should suggest 0 and -1 for int parameters
    param_names = [h.param_name for h in suggestion.hypotheses]
    assert "total" in param_names
    assert "count" in param_names
    edge_vals = [h.edge_value_repr for h in suggestion.hypotheses]
    assert "0" in edge_vals
    assert "-1" in edge_vals


def test_test_suggester_string_and_list():
    suggester = LayaTestSuggester()

    code = """
def parse_tags(payload: str, defaults: list[str]) -> list[str]:
    return payload.split(",") if payload else defaults
"""
    suggestion = suggester.analyze_function(code)

    assert suggestion.target_function == "parse_tags"
    edge_vals = [h.edge_value_repr for h in suggestion.hypotheses]
    assert '""' in edge_vals
    assert "[]" in edge_vals
    assert "def test_parse_tags_edge_cases():" in suggestion.suggested_test_code
