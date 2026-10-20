from types import SimpleNamespace

import pytest

from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize(
    ("method", "payload", "alias"),
    [
        (LocalAIServices.reason, {"problem": "current", "task": "retired"}, "task"),
        (LocalAIServices.review, {"code": "current", "context": "retired"}, "context"),
    ],
)
def test_semantic_services_reject_retired_input_aliases_before_delegation(method, payload, alias):
    calls = []
    services = SimpleNamespace(delegate=lambda *args: calls.append(args))

    result = method(services, payload)

    assert result["success"] is False
    assert alias in result["error"]
    assert calls == []


@pytest.mark.parametrize(
    ("method", "payload", "expected_task", "expected_context"),
    [
        (LocalAIServices.reason, {"problem": "explain", "context": "evidence"}, "explain", "evidence"),
        (
            LocalAIServices.review,
            {"code": "source", "instructions": "find defects"},
            "find defects",
            "source",
        ),
    ],
)
def test_semantic_services_translate_only_canonical_http_fields(
    method, payload, expected_task, expected_context
):
    calls = []
    expected = {"success": True, "text": "done"}

    def delegate(request):
        calls.append(request)
        return expected

    services = SimpleNamespace(delegate=delegate)

    result = method(services, payload)

    if method is LocalAIServices.review:
        assert result is not expected
        assert result["success"] is True and result["text"] == expected["text"]
        assert result["advisory_only"] is True
        assert result["review_consistency"]["status"] == "unverified"
        assert result["review_consistency"]["semantic_truth_verified"] is False
        assert expected == {"success": True, "text": "done"}
    else:
        assert result is expected
    assert calls[0]["task"] == expected_task
    assert calls[0]["context"] == expected_context
    assert "problem" not in calls[0]
    assert "code" not in calls[0]

@pytest.mark.parametrize(
    ("method", "payload", "alias"),
    [
        (LocalAIServices.delegate, {"task": "current", "prompt": "retired"}, "prompt"),
        (LocalAIServices.speculative_draft, {"task": "current", "path": "retired"}, "path"),
        (LocalAIServices.speculative_draft, {"task": "current", "cwd": "retired"}, "cwd"),
        (LocalAIServices.task_scaffold, {"prompt": "current", "task": "retired"}, "task"),
        (LocalAIServices.task_scaffold, {"prompt": "current", "spec": "retired"}, "spec"),
    ],
)
def test_semantic_services_reject_retired_dispatch_aliases_before_work(method, payload, alias):
    resolution_calls = []

    def resolve_project(_root):
        resolution_calls.append(True)
        return None, "", "", ""

    result = method(SimpleNamespace(_resolve_local_task_project=resolve_project), payload)

    assert result["success"] is False
    assert alias in result["error"]
    assert resolution_calls == []
