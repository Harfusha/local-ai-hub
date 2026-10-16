from __future__ import annotations

import math
from typing import Any
import pytest

from local_ai_hub.tool_agent import ToolAwareLocalAgent, _safe_int, _safe_float
from local_ai_hub.trace_context import (
    clear_context,
    current,
    current_agent,
    current_request_id,
    current_tenant,
    current_trace_id,
    has_context,
    is_trace_active,
    set_context,
    set_metadata,
    scoped_context,
    _sanitize_ident,
)


class DummyServices:
    def __init__(self) -> None:
        self.config = {}


class DummyPreprocessor:
    def lookup(self, root: str, query: str, limit: int = 5) -> dict[str, Any]:
        return {"root": root, "query": query, "limit": limit}


class DummyRag:
    def search(self, query: str, tenant: str, workspace: str, limit: int, flag: bool) -> dict[str, Any]:
        return {"query": query, "results": []}


def test_safe_numeric_helpers() -> None:
    assert _safe_int(10) == 10
    assert _safe_int(True, default=5) == 5
    assert _safe_int(False, default=5) == 5
    assert _safe_int(float("nan"), default=7) == 7
    assert _safe_int(float("inf"), default=7) == 7
    assert _safe_int("42") == 42
    assert _safe_int("invalid", default=3) == 3
    assert _safe_int(-5, default=1, min_val=1) == 1
    assert _safe_int(100, default=1, max_val=50) == 50

    assert _safe_float(3.14) == 3.14
    assert _safe_float(True, default=1.0) == 1.0
    assert _safe_float(float("nan"), default=0.5) == 0.5
    assert _safe_float(float("inf"), default=0.5) == 0.5
    assert _safe_float("2.5") == 2.5
    assert _safe_float("bad", default=0.1) == 0.1
    assert _safe_float(-1.0, default=0.0, min_val=0.0) == 0.0
    assert _safe_float(2.0, default=1.0, max_val=1.0) == 1.0


def test_tool_aware_local_agent_init_defensive() -> None:
    # None config or malformed config
    agent = ToolAwareLocalAgent(
        None,  # type: ignore[arg-type]
        DummyServices(),
        DummyPreprocessor(),
        DummyRag(),
    )
    assert agent.enabled is True
    assert agent.max_steps == 4
    assert agent.max_calls == 8
    assert agent.max_tool_chars == 6500
    assert agent.pre_context_chars == 2800
    assert agent.semantic_bypass_confidence == 0.94
    assert agent.is_enabled() is True
    assert agent.total_runs() == 0

    # Malformed local_tools values
    bad_cfg = {
        "local_tools": {
            "enabled": True,
            "max_steps": float("nan"),
            "max_tool_calls": -99,
            "max_tool_result_chars": "invalid",
            "preprocessed_context_chars": float("inf"),
            "semantic_bypass_confidence": 2.5,  # must be clamped to 1.0
        }
    }
    agent2 = ToolAwareLocalAgent(
        bad_cfg,
        DummyServices(),
        DummyPreprocessor(),
        DummyRag(),
    )
    assert agent2.max_steps == 4
    assert agent2.max_calls == 1  # clamped to min_val 1
    assert agent2.max_tool_chars == 6500
    assert agent2.pre_context_chars == 2800
    assert agent2.semantic_bypass_confidence == 1.0


def test_tool_aware_local_agent_inspection_and_clear_stats() -> None:
    agent = ToolAwareLocalAgent(
        {},
        DummyServices(),
        DummyPreprocessor(),
        DummyRag(),
    )
    agent.runs = 5
    agent.cache_hits = 3
    agent.tool_calls = 10
    agent.failures = 1
    agent.semantic_bypasses = 2
    assert agent.total_runs() == 5

    agent.clear_stats()
    assert agent.total_runs() == 0
    assert agent.runs == 0
    assert agent.cache_hits == 0
    assert agent.tool_calls == 0
    assert agent.failures == 0
    assert agent.semantic_bypasses == 0


def test_tool_aware_local_agent_arguments_sanitization() -> None:
    agent = ToolAwareLocalAgent({}, DummyServices(), DummyPreprocessor(), DummyRag())
    # Not a dict
    assert agent._arguments("invalid") == {}  # type: ignore[arg-type]
    assert agent._arguments(None) == {}  # type: ignore[arg-type]
    # Function with invalid json or null bytes
    call_invalid_json = {"function": {"arguments": "{\"bad: json\x00"}}
    assert agent._arguments(call_invalid_json) == {}
    call_valid = {"function": {"arguments": "{\"key\": \"val\"}"}}
    assert agent._arguments(call_valid) == {"key": "val"}


def test_tool_aware_local_agent_execute_tool_sanitization() -> None:
    agent = ToolAwareLocalAgent({}, DummyServices(), DummyPreprocessor(), DummyRag())
    # Null byte in tool name
    res = agent._execute_tool("preprocessed_context\x00", {"query": "test\x00"}, "C:/root", "tenant", "ws")
    assert res.get("query") == "test"

    # Non-dict args
    res2 = agent._execute_tool("preprocessed_context", None, "C:/root", "tenant", "ws")  # type: ignore[arg-type]
    assert res2.get("query") == ""

    # Unknown tool
    res3 = agent._execute_tool("nonexistent_tool", {}, "C:/root", "tenant", "ws")
    assert res3["success"] is False
    assert "unknown local tool" in res3["error"]


def test_trace_context_sanitize_ident_edge_cases() -> None:
    # NaN, Inf, negative limit
    for limit in (float("nan"), -5, True):
        with pytest.raises(ValueError):
            _sanitize_ident("hello world", limit=limit)
    assert _sanitize_ident("hello world", limit=5) == "hello"
    assert _sanitize_ident(None) == ""
    assert _sanitize_ident("abc\x00def") == "abcdef"


def test_trace_context_set_metadata_non_mapping() -> None:
    clear_context()
    # Non-mapping input must not crash
    token = set_metadata("not-a-mapping")  # type: ignore[arg-type]
    assert token is not None
    token2 = set_metadata(12345)  # type: ignore[arg-type]
    assert token2 is not None
    token3 = set_metadata([("a", 1)])  # type: ignore[arg-type]
    assert token3 is not None
    clear_context()


def test_trace_context_helpers() -> None:
    clear_context()
    assert has_context() is False
    assert is_trace_active() is False
    assert current_request_id() == ""
    assert current_trace_id() == ""
    assert current_agent() == ""
    assert current_tenant() == ""

    with scoped_context(request_id="req-99", trace_id="tr-88", agent="ag-77", tenant="ten-66"):
        assert has_context() is True
        assert is_trace_active() is True
        assert current_request_id() == "req-99"
        assert current_trace_id() == "tr-88"
        assert current_agent() == "ag-77"
        assert current_tenant() == "ten-66"

    assert has_context() is False
    assert is_trace_active() is False
