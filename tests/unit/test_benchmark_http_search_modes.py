from __future__ import annotations

import pytest

from tools.benchmark_http_search import build_search_payload


def test_default_benchmark_payload_uses_endpoint_default_mode():
    assert build_search_payload("C:/repo", "Local AI Hub installation", "default") == {
        "root": "C:/repo",
        "query": "Local AI Hub installation",
        "limit": 10,
    }


@pytest.mark.parametrize("mode", ["lexical", "rag", "hybrid"])
def test_benchmark_payload_can_select_an_explicit_search_mode(mode: str):
    assert build_search_payload("C:/repo", "C++", mode) == {
        "root": "C:/repo",
        "query": "C++",
        "limit": 10,
        "search_mode": mode,
    }


def test_benchmark_rejects_unknown_search_mode():
    with pytest.raises(ValueError, match="search_mode"):
        build_search_payload("C:/repo", "query", "semantic")
