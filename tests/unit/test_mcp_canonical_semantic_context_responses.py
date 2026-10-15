"""Deferred current-protocol boundary tests with fake transport only."""

from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server


def canonical_context():
    return {
        "success": True, "complete": True, "text": "current context",
        "context_id": "context-1", "etag": "etag-1", "evidence_ids": ["E-1"],
    }


def load_context(monkeypatch, tmp_path, response):
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(post=lambda *a, **k: response))
    return mcp_server._load_task_context(task_id="task-1", root=str(tmp_path), context="input")


@pytest.mark.parametrize("response", [
    {"success": True, "complete": True, "text": "old flat context"},
    {"success": True, "task_context": canonical_context()},
    {"success": 1, "complete": True, "task_context": canonical_context()},
    {"success": True, "complete": "true", "task_context": canonical_context()},
    {"success": True, "complete": True, "task_context": {"text": "partial"}},
    {"success": True, "complete": True, "task_context": {**canonical_context(), "text": 7}},
])
def test_context_protocol_rejects_missing_or_coercive_fields(monkeypatch, tmp_path, response):
    text, metadata = load_context(monkeypatch, tmp_path, response)
    assert text == ""
    assert metadata["success"] is False
    assert metadata["terminal"] is True
    assert metadata["retryable"] is False


def test_context_uses_nested_text_and_preserves_current_receipt(monkeypatch, tmp_path):
    response = {"success": True, "complete": True, "text": "unused flat text", "task_context": canonical_context()}
    text, metadata = load_context(monkeypatch, tmp_path, response)
    assert "current context" in text and "unused flat text" not in text
    assert metadata == {"success": True, "context_id": "context-1", "etag": "etag-1", "evidence_ids": ["E-1"]}


def test_context_preserves_actual_retryable_failure(monkeypatch, tmp_path):
    text, metadata = load_context(monkeypatch, tmp_path, {
        "success": False, "terminal": False, "retryable": True, "error": "busy",
    })
    assert text == "" and metadata["error"] == "busy"
    assert metadata["retryable"] is True


@pytest.mark.parametrize("value", ["raw text", {"text": "implicit success"}, {"success": 1, "text": "coerced"}])
def test_semantic_status_must_be_explicit_boolean(value):
    result = mcp_server._quality_check_semantic_result(value, task="review", context="")
    assert result["success"] is False and result["error_code"] == "invalid_semantic_result"


def test_answer_is_not_a_semantic_text_alias():
    result = mcp_server._quality_check_semantic_result({"success": True, "answer": "old"}, task="review", context="")
    assert result["success"] is False and result["error_code"] == "empty_semantic_result"
    assert "text" not in result


def test_canonical_semantic_text_and_explicit_failure_remain_supported():
    for value in ({"success": True, "text": "current"}, {"success": False, "retryable": True, "error": "busy"}):
        assert mcp_server._quality_check_semantic_result(value, task="review", context="") == value
