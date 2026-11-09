import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.token_accounting import json_tokens


@pytest.fixture(autouse=True)
def qualified_batch_actions(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, "tasks", True)
    monkeypatch.setattr(mcp_server.FEATURES, "hardware_profile", "balanced")
    monkeypatch.setattr(mcp_server.FEATURES, "local_semantic_analysis", True)
    monkeypatch.setattr(mcp_server.FEATURES, "has_any_model", lambda: True)


def batch_result():
    return {
        "success": True, "input_count": 3, "accepted_count": 3,
        "rejected_count": 0, "rejected_indices": [],
        "results": [{"success": True, "id": f"item-{i}", "text": "x" * 5000} for i in range(3)],
    }


@pytest.mark.parametrize("limit", [128, 256])
def test_batch_projection_does_not_hide_dispatched_outcome(monkeypatch, limit):
    calls = []
    def post(path, payload, **kwargs):
        calls.append(path)
        return batch_result()
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_task(
        action="batch", tasks=[{"id": f"item-{i}", "task": "work"} for i in range(3)],
        max_response_tokens=limit,
    )
    assert calls.count("/api/delegate/batch") == 1
    if result.get("success") is False:
        assert result.get("outcome_unknown") is True
        assert result.get("request_not_sent") is not True
    else:
        assert len(result["results"]) == 3

    content, structured = mcp_server._mcp_budget_payload(
        "local_ai_task", {"action": "batch", "max_response_tokens": limit}, result,
    )
    assert structured is not None
    assert structured.get("outcome_unknown") is True or len(structured.get("results", [])) == 3
    if structured.get("outcome_unknown") is True:
        assert json.loads(content[0].text)["outcome_unknown"] is True
    wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in content],
            "structuredContent": structured, "isError": False}
    assert json_tokens(wire) <= limit


@pytest.mark.parametrize("limit", [128, 256, 512])
def test_wire_projection_preserves_batch_outcome_when_items_do_not_fit(limit):
    content, structured = mcp_server._mcp_budget_payload(
        "local_ai_task", {"action": "batch", "max_response_tokens": limit}, batch_result(),
    )
    assert structured is not None
    assert structured.get("outcome_unknown") is True or len(structured.get("results", [])) == 3
    if structured.get("outcome_unknown") is True:
        assert json.loads(content[0].text)["outcome_unknown"] is True
    wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in content],
            "structuredContent": structured, "isError": False}
    assert json_tokens(wire) <= limit


def test_wire_keeps_request_identity_and_no_retry_signal_at_minimum_budget():
    value = {**batch_result(), "request_id": "req_0123456789ab"}
    _, structured = mcp_server._mcp_budget_payload(
        "local_ai_task", {"action": "batch", "max_response_tokens": 128}, value,
    )
    assert structured["outcome_unknown"] is True
    assert structured["request_id"] == value["request_id"]


def test_pre_dispatch_refusal_never_claims_uncertain_execution():
    value = {"success": False, "error": "invalid batch", "request_not_sent": True,
             "results": [], "rejected_indices": list(range(100))}
    content, structured = mcp_server._mcp_budget_payload(
        "local_ai_task", {"action": "batch", "max_response_tokens": 128}, value,
    )
    assert structured["request_not_sent"] is True
    assert structured.get("outcome_unknown") is not True
    assert json.loads(content[0].text)["request_not_sent"] is True


def test_batch_items_are_retained_when_budget_suffices(monkeypatch):
    small = {**batch_result(), "results": [
        {"id": f"item-{i}", "success": True, "text": "answer"} for i in range(3)
    ]}
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: small)
    result = mcp_server.local_ai_task(
        action="batch", tasks=[{"id": f"item-{i}", "task": "work"} for i in range(3)],
        max_response_tokens=4096,
    )
    assert result["success"] is True
    assert result["results"] == small["results"]
