from types import SimpleNamespace

import pytest

from local_ai_hub.pipeline import LocalAgentPipeline


def _pipeline(tmp_path, stage_result):
    class Services:
        config = {"security": {"allowed_roots": [str(tmp_path)]}}
        router = SimpleNamespace(classify=lambda *_args: {"complexity": "simple", "task_type": "question"})
        deterministic = None
        code_index = None

        def _hybrid_context(self, root, task, **_kwargs):
            return {"success": True, "root": root, "context": "", "evidence": []}

        def _repo_cache_state(self, root):
            return {}

    config = {"server": {"state_dir": str(tmp_path)}, "models": {"fast_code": "fast", "heavy_code": "heavy", "reasoning": "reason"}}
    stage_result = {"tool_agent_cache": {"hit": False, "coalesced": False}, **stage_result}
    agent = SimpleNamespace(run=lambda *_args, **_kwargs: dict(stage_result))
    pipeline = LocalAgentPipeline(config, Services(), None, agent)
    pipeline.planner = SimpleNamespace(plan=lambda *_args: {"explorer": True, "worker": False, "critic": False, "confidence": 0.0})
    pipeline._stage = lambda _key, compute: {**compute(), "stage_cache_hit": False, "stage_coalesced": False}
    return pipeline


def test_pipeline_preserves_observed_tool_evidence(tmp_path):
    counts = {"attempted": 1, "completed": 1, "failed": 0, "unknown": 0}
    pipeline = _pipeline(tmp_path, {"success": True, "text": "answer", "model": "fast", "tool_agent": {"tool_evidence": counts}})
    result = pipeline.solve_repo({"root": str(tmp_path), "task": "find symbol"})
    assert result["tool_evidence"]["explorer"]["counts"] == counts
    assert result["tool_evidence"]["explorer"]["reuse"] == "fresh"
    assert "worker" not in result["tool_evidence"]


def test_pipeline_passes_laya_tool_output_callback_only_with_task_and_retrieved_evidence(tmp_path):
    pipeline = _pipeline(tmp_path, {"success": True, "text": "answer", "model": "fast"})
    pipeline.services._hybrid_context = lambda *_args, **_kwargs: {
        "success": True,
        "root": str(tmp_path),
        "context": "verified excerpt",
        "evidence": [{"evidence_id": "ev-pipeline"}],
    }
    callback = lambda *_args: None
    seen = []
    pipeline.tool_agent.run = lambda *_args, **kwargs: (
        seen.append(kwargs.get("laya_tool_output_callback"))
        or {"success": True, "text": "answer", "model": "fast"}
    )

    pipeline.solve_repo({
        "root": str(tmp_path),
        "task": "find symbol",
        "task_id": "task-pipeline",
        "_laya_tool_output_callback": callback,
    })
    pipeline.solve_repo({
        "root": str(tmp_path),
        "task": "find symbol",
        "_laya_tool_output_callback": callback,
    })

    assert seen == [callback, None]


@pytest.mark.parametrize("value", [None, {}, {"attempted": True, "completed": 1, "failed": 0, "unknown": 0},
                                  {"attempted": 1, "completed": 1, "failed": 1, "unknown": 0}])
def test_pipeline_does_not_invent_missing_or_malformed_tool_evidence(tmp_path, value):
    pipeline = _pipeline(tmp_path, {"success": True, "text": "answer", "tool_agent": {"tool_evidence": value}})
    result = pipeline.solve_repo({"root": str(tmp_path), "task": "find symbol"})
    assert result["tool_evidence"]["explorer"] is None


def test_pipeline_marks_cached_tool_evidence_as_reused(tmp_path):
    counts = {"attempted": 1, "completed": 1, "failed": 0, "unknown": 0}
    pipeline = _pipeline(tmp_path, {"success": True, "text": "answer", "tool_agent": {"tool_evidence": counts}, "tool_agent_cache": {"hit": True}})
    result = pipeline.solve_repo({"root": str(tmp_path), "task": "find symbol"})
    assert result["tool_evidence"]["explorer"]["reuse"] == "cached"


def test_pipeline_marks_coalesced_tool_evidence_as_reused(tmp_path):
    counts = {"attempted": 0, "completed": 0, "failed": 0, "unknown": 0}
    pipeline = _pipeline(tmp_path, {"success": True, "text": "answer", "tool_agent": {"tool_evidence": counts}})
    pipeline._stage = lambda _key, compute: {**compute(), "stage_cache_hit": False, "stage_coalesced": True}
    result = pipeline.solve_repo({"root": str(tmp_path), "task": "find symbol"})
    assert result["tool_evidence"]["explorer"]["reuse"] == "coalesced"


def test_mcp_compact_solve_retains_evidence_with_budget(tmp_path):
    from local_ai_hub import mcp_server
    from local_ai_hub.response_budget import json_tokens

    counts = {"attempted": 1, "completed": 0, "failed": 1, "unknown": 0}
    pipeline = _pipeline(tmp_path, {"success": True, "text": "answer", "tool_agent": {"tool_evidence": counts}})
    result = pipeline.solve_repo({"root": str(tmp_path), "task": "find symbol"})
    result["canonical"]["large_detail"] = "x" * 10000
    token = mcp_server._CURRENT_RESPONSE_OPTIONS.set({"max_response_tokens": 1200, "response_profile": "compact"})
    try:
        compacted = mcp_server._compact(result, "solve")
    finally:
        mcp_server._CURRENT_RESPONSE_OPTIONS.reset(token)
    assert compacted["tool_evidence"]["explorer"]["counts"] == counts
    assert json_tokens(compacted) <= 1200


def test_mcp_solve_tool_returns_pipeline_evidence(tmp_path, monkeypatch):
    import asyncio
    from local_ai_hub import mcp_server

    counts = {"attempted": 1, "completed": 0, "failed": 1, "unknown": 0}
    pipeline = _pipeline(tmp_path, {"success": True, "text": "answer", "tool_agent": {"tool_evidence": counts}})
    result = pipeline.solve_repo({"root": str(tmp_path), "task": "find symbol"})
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda path, payload, **kwargs: result)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", "high")
    monkeypatch.setattr(mcp_server.FEATURES, "local_semantic_analysis", True)
    response = mcp_server.local_ai_repo(
        action="solve", root=str(tmp_path), task="find symbol", max_response_tokens=1600,
    )
    assert response["tool_evidence"]["explorer"]["counts"] == counts
