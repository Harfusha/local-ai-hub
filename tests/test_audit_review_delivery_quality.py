from __future__ import annotations

import asyncio
import copy
import json

import pytest

from local_ai_hub.services import LocalAIServices


PATH = "src/example.py"
CONTRADICTORY = json.dumps({"verdict": "pass", "findings": [
    {"citation": {"path": PATH, "line": 1}, "description": "Defect"},
]})


def deliver(text, quality=None):
    service = object.__new__(LocalAIServices)
    payload = {"success": True, "text": text, "semantic_quality": quality or {
        "usable": True, "reason": "shape_checked", "advisory_only": True,
        "semantic_truth_verified": False,
    }}
    service.delegate = lambda _args: copy.deepcopy(payload)
    return service.review({"code": "pass", "changed_paths": [PATH]})


@pytest.mark.parametrize("text", [CONTRADICTORY, "Review prose without a structured verdict."])
def test_service_review_rejection_also_rejects_semantic_quality(text):
    result = deliver(text)
    assert result["success"] is True  # Transport success is independent.
    assert result["review_consistency"]["usable"] is False
    assert result["semantic_quality"]["usable"] is False
    assert result["semantic_quality"]["semantic_truth_verified"] is False


def test_structurally_valid_review_cannot_upgrade_prior_quality_rejection():
    result = deliver('{"verdict":"pass","findings":[]}', {
        "usable": False, "reason": "unrelated_output", "advisory_only": True,
        "semantic_truth_verified": False,
    })
    assert result["review_consistency"]["usable"] is True
    assert result["semantic_quality"]["usable"] is False
    assert result["semantic_quality"]["reason"] == "unrelated_output"


@pytest.mark.parametrize("budget", [3200, 1024, 128])
@pytest.mark.parametrize("profile", ["compact", "minimal"])
def test_actual_mcp_review_wire_preserves_rejected_quality(monkeypatch, budget, profile):
    from local_ai_hub import mcp_server
    from local_ai_hub.token_accounting import json_tokens

    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)
    response = deliver(CONTRADICTORY)
    # Independent server rejection: the MCP boundary must never recompute it away.
    response["semantic_quality"].update(usable=False, reason="verdict_contradiction")
    requests = []
    def post(path, payload, **kwargs):
        requests.append(path)
        return copy.deepcopy(response)
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda event: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, "record", lambda **kwargs: None)
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_task", {
        "action": "review", "task": "Review src/example.py", "context": "src/example.py:1 pass",
        "changed_paths": [PATH], "response_profile": profile, "max_response_tokens": budget,
    }))
    assert requests == ["/api/review"]
    if isinstance(result, tuple):
        content, structured = result
    else:
        content, structured = result, None
    wire = {"content": [{"type": "text", "text": part.text} for part in content]}
    if structured is not None:
        wire.update(structuredContent=structured, isError=False)
    assert json_tokens(wire) <= budget
    parsed = structured if structured is not None else json.loads(content[0].text)
    if parsed.get("success") is False:
        assert parsed.get("error") == "max_response_tokens too small"
    else:
        assert parsed["advisory_only"] is True
        assert parsed["semantic_quality"]["usable"] is False
        assert parsed["review_consistency"]["usable"] is False


@pytest.mark.parametrize("prior", [None, {}, {"usable": 1}, {"usable": "false"}])
def test_mcp_does_not_replace_malformed_present_quality_with_positive_gate(prior):
    from local_ai_hub import mcp_server
    result = mcp_server._quality_check_semantic_result(
        {"success": True, "text": "Review src/example.py:1 for defects.", "semantic_quality": prior},
        task="Review src/example.py", context="src/example.py", changed_paths=[PATH],
    )
    assert result["semantic_quality"]["usable"] is False


def test_mcp_shape_check_cannot_upgrade_validly_shaped_rejected_review():
    from local_ai_hub import mcp_server
    from local_ai_hub.semantic_quality import assess_semantic_result
    response = {"success": True, "text": "Review src/example.py:1 for defects.",
                "semantic_quality": {"usable": False, "reason": "verdict_contradiction"},
                "review_consistency": {"usable": False, "reason": "verdict_contradiction"}}
    assert assess_semantic_result("Review source", [PATH], response)["usable"] is True
    result = mcp_server._quality_check_semantic_result(
        response, task="Review source", context=PATH, changed_paths=[PATH],
    )
    assert result["semantic_quality"]["usable"] is False
    assert result["semantic_quality"]["reason"] == "verdict_contradiction"


def test_mcp_review_gate_survives_without_path_hints():
    from local_ai_hub import mcp_server
    result = mcp_server._quality_check_semantic_result(
        {"success": True, "text": "Review complete.", "semantic_quality": {"usable": True},
         "review_consistency": {"usable": False, "reason": "verdict_contradiction"}},
        task="Review source", context="", changed_paths=[],
    )
    assert result["semantic_quality"]["usable"] is False
    assert result["semantic_quality"]["reason"] == "verdict_contradiction"
