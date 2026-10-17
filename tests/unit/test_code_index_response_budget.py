from __future__ import annotations

import asyncio
import json

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


def test_code_index_keeps_one_symbol_under_budget_when_more_pages_have_large_metadata():
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
        "coverage": {"matched_terms": ["generate", "tests"] * 500},
        "freshness": {"unknown_paths": [f"src/module_{i}.py" for i in range(500)]},
        "parse_outcomes": [{"path": f"src/module_{i}.py", "status": "parsed"} for i in range(500)],
        "truncation": {"debug": "x" * 5000},
    }

    result = _code_index_prefix_fitting(
        base,
        base,
        [symbol],
        1200,
        wire_budget=True,
    )

    assert result is not None
    assert result["success"] is True
    assert result["symbols"][0]["name"] == "generate_tests"
    assert result["symbols"][0]["path"] == "src/local_ai_hub/builder.py"
    assert result["symbols"][0]["line"] == 120
    assert result["has_more"] is True
    assert result["next_offset"] == 1


def test_registered_code_index_returns_bounded_symbol_instead_of_413(tmp_path, monkeypatch):
    from local_ai_hub import mcp_server
    from local_ai_hub.features import FeatureSet

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
    raw = {
        "success": True,
        "request_id": "req-f12-wire",
        "root": str(tmp_path / "wrong-scope"),
        "query": "wrong-query",
        "terms": ["generate", "tests"],
        "limit": 24,
        "offset": 0,
        "total_matches": 7941,
        "has_more": True,
        "symbols": [symbol],
        "coverage": {"matched_terms": ["generate", "tests"] * 500},
        "freshness": {"unknown_paths": [f"src/module_{i}.py" for i in range(500)]},
        "parse_outcomes": [{"path": f"src/module_{i}.py", "status": "parsed"} for i in range(500)],
        "truncation": {"debug": "x" * 5000},
    }

    monkeypatch.setattr(mcp_server, "_workspace", str(tmp_path))
    monkeypatch.setattr(mcp_server, "FEATURES", FeatureSet({}))
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **_kwargs: None)
    monkeypatch.setattr(
        mcp_server, "load_operational_mode",
        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot("active", 0, None),
    )

    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "code_index",
        "root": str(tmp_path),
        "query": "generate_tests",
        "max_response_tokens": 1200,
    }))
    contents, structured = result if isinstance(result, tuple) else (result, None)
    payload = json.loads(contents[0].text)
    wire = {"content": [{"type": "text", "text": contents[0].text}]}
    if structured is not None:
        wire.update(structuredContent=structured, isError=False)

    assert payload["success"] is True, payload
    assert payload["request_id"] == "req-f12-wire"
    assert payload["root"] == str(tmp_path)
    assert payload["query"] == "generate_tests"
    assert payload["symbols"][0]["name"] == "generate_tests"
    assert payload["symbols"][0]["path"] == "src/local_ai_hub/builder.py"
    assert payload["symbols"][0]["line"] == 120
    assert payload["has_more"] is True
    assert payload["next_offset"] == 1
    assert payload["response_budget"]["requested_tokens"] == 1200
    assert payload["response_budget"]["returned_tokens"] <= 1200
    assert payload["response_budget"]["unit"] == "estimated_tokens"
