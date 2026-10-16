from __future__ import annotations

from local_ai_hub.code_index import _code_index_candidate_score
from local_ai_hub.mcp_server import _code_index_prefix_fitting


def test_code_index_exact_identifier_ranks_above_token_matches():
    exact = _code_index_candidate_score(
        "generate_tests", "Builder.generate_tests", "Builder", "src/builder.py",
        ["generate", "tests"], "generate_tests",
    )
    partial = _code_index_candidate_score(
        "generate_test_report", "Builder.generate_test_report", "Builder", "src/builder.py",
        ["generate", "tests"], "generate_tests",
    )

    assert exact > partial


def test_code_index_returns_minimal_exact_symbol_when_full_detail_exceeds_budget():
    symbol = {
        "name": "generate_tests",
        "name_path": "Builder.generate_tests",
        "kind": "method",
        "path": "src/local_ai_hub/builder.py",
        "line": 120,
        "end_line": 170,
        "container": "Builder",
        "signature": "generate_tests(" + ("x" * 15_000) + ")",
        "access": "public",
        "score": 12.0,
        "matched_terms": ["generate", "tests"],
    }
    base = {
        "success": True,
        "root": "C:/repo",
        "query": "generate_tests",
        "terms": ["generate", "tests"],
        "limit": 24,
        "offset": 0,
        "total_matches": 7941,
        "has_more": True,
        "symbols": [symbol],
        "coverage": {"query_term_coverage": 1.0},
        "freshness": {"status": "not_checked"},
        "truncation": {},
    }

    result = _code_index_prefix_fitting(
        base,
        base,
        [symbol],
        1800,
        wire_budget=True,
    )

    assert result is not None
    assert result["success"] is True
    assert result["symbols"][0]["name"] == "generate_tests"
    assert result["symbols"][0]["path"] == "src/local_ai_hub/builder.py"
    assert result["symbols"][0]["line"] == 120
    assert result["has_more"] is True
    assert result["next_offset"] == 1
    assert "symbols.signature" in result["omitted_fields"]
