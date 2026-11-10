import pytest

from local_ai_hub.laya_decisions import (
    DecisionCategory,
    DecisionMode,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
)


def test_request_accepts_only_closed_categories_and_authorized_evidence_ids():
    request = DecisionRequest.from_mapping(
        {
            "category": "context_source",
            "evidence_ids": ["ev-1"],
            "options": ["indexed", "artifact", "memory"],
        },
        decision_id="dec-1",
        mode=DecisionMode.ADVISORY,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
    )

    assert request.category is DecisionCategory.CONTEXT_SOURCE
    assert request.evidence_ids == ("ev-1",)
    assert request.mode is DecisionMode.ADVISORY


@pytest.mark.parametrize(
    "override",
    [
        {"category": "decide_anything"},
        {"repository_id": ""},
        {"evidence_ids": ["ev-1", "ev-1"]},
        {"options": ["indexed", "indexed"]},
        {"transcript": "private prompt"},
        {"mode": "advisory"},
        {"repository_id": "other-repo"},
        {"task_id": "task-spoof"},
        {"session_id": "session-spoof"},
    ],
)
def test_request_rejects_aliases_raw_content_and_malformed_identity(override):
    payload = {
        "category": "context_source",
        "evidence_ids": ["ev-1"],
        "options": ["indexed", "artifact"],
    }
    payload.update(override)

    with pytest.raises(ValueError):
        DecisionRequest.from_mapping(
            payload,
            decision_id="dec-1",
            mode=DecisionMode.SHADOW,
            repository_id="repo-1",
            task_id=None,
            session_id="session-1",
        )


def test_result_rejects_suggestion_outside_options_and_projects_metadata_only():
    request = DecisionRequest.from_mapping(
        {"category": "context_source", "evidence_ids": ["ev-2"], "options": ["indexed", "artifact"]},
        decision_id="dec-2",
        mode=DecisionMode.SHADOW,
        repository_id="repo-1",
        task_id=None,
        session_id="session-1",
    )
    with pytest.raises(ValueError):
        DecisionResult.from_mapping(
            request,
            {"success": True, "status": "success", "suggestion": "memory", "reason_codes": []},
        )
    with pytest.raises(ValueError, match="outside the permitted options"):
        DecisionResult(
            request=request,
            success=True,
            status=DecisionStatus.SUCCESS,
            suggestion="stop",
            reason_codes=(),
        )

    result = DecisionResult.from_mapping(
        request,
        {"success": True, "status": "success", "suggestion": "indexed", "reason_codes": ["EVIDENCE_SUFFICIENT"]},
    )
    metadata = result.metadata()

    assert metadata["mode"] == "shadow"
    assert metadata["category"] == "context_source"
    assert metadata["evidence_ids"] == ["ev-2"]
    assert metadata["model_estimate"] is True
    assert metadata["execution_verification"] == "NOT_VERIFIED"
    assert "raw_output" not in metadata


def test_abstention_has_no_suggestion_and_failure_is_explicit():
    request = DecisionRequest.from_mapping(
        {"category": "next_step", "evidence_ids": [], "options": ["inspect_source", "run_test"]},
        decision_id="dec-3",
        mode=DecisionMode.ADVISORY,
        repository_id="repo-1",
        task_id="task-3",
        session_id="session-3",
    )
    result = DecisionResult.from_mapping(
        request,
        {"success": True, "status": "abstain", "suggestion": None, "reason_codes": ["INSUFFICIENT_EVIDENCE"]},
    )

    assert result.status is DecisionStatus.ABSTAIN
    assert result.suggestion is None
    assert result.metadata()["success"] is True


def test_request_rejects_options_outside_category_allowlist():
    with pytest.raises(ValueError, match="unsupported decision option"):
        DecisionRequest.from_mapping(
            {"category": "context_source", "evidence_ids": [], "options": ["stop", "indexed"]},
            decision_id="dec-4",
            mode=DecisionMode.ADVISORY,
            repository_id="repo-1",
            task_id=None,
            session_id="session-1",
        )


def test_abstention_is_a_result_status_not_a_decision_option():
    with pytest.raises(ValueError, match="unsupported decision option"):
        DecisionRequest.from_mapping(
            {"category": "context_source", "evidence_ids": [], "options": ["abstain"]},
            decision_id="dec-5",
            mode=DecisionMode.ADVISORY,
            repository_id="repo-1",
            task_id=None,
            session_id="session-1",
        )

    with pytest.raises(ValueError, match="unsupported decision option"):
        DecisionRequest(
            decision_id="dec-direct",
            mode=DecisionMode.ADVISORY,
            category=DecisionCategory.CONTEXT_SOURCE,
            repository_id="repo-1",
            task_id=None,
            session_id="session-direct",
            evidence_ids=(),
            options=("stop",),
        )


@pytest.mark.parametrize(
    ("category", "option"),
    [
        ("context_source", "abstain"),
        ("completion_gap", "verified"),
        ("redundant_step", "skip_repeat"),
        ("watchdog", "stop"),
        ("watchdog", "continue"),
    ],
)
def test_category_options_never_claim_completion_or_encode_executable_watchdog_actions(category, option):
    with pytest.raises(ValueError, match="unsupported decision option"):
        DecisionRequest.from_mapping(
            {"category": category, "evidence_ids": [], "options": [option]},
            decision_id="dec-safe-options",
            mode=DecisionMode.SHADOW,
            repository_id="repo-1",
            task_id=None,
            session_id="session-safe-options",
        )


def test_watchdog_options_are_explicitly_non_authoritative_recommendations():
    request = DecisionRequest.from_mapping(
        {"category": "watchdog", "evidence_ids": ["ev-1"], "options": ["recommend_stop"]},
        decision_id="dec-watchdog",
        mode=DecisionMode.SHADOW,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
    )

    result = DecisionResult.from_mapping(
        request,
        {"success": True, "status": "success", "suggestion": "recommend_stop", "reason_codes": ["LOW_SIGNAL"]},
    )

    assert result.suggestion == "recommend_stop"
    assert result.metadata()["model_estimate"] is True
    assert result.metadata()["execution_verification"] == "NOT_VERIFIED"


def test_redundant_work_category_reports_signal_without_skipping_validation():
    request = DecisionRequest.from_mapping(
        {
            "category": "redundant_step",
            "evidence_ids": ["ev-1"],
            "options": ["possible_duplicate", "validation_still_required"],
        },
        decision_id="dec-duplicate",
        mode=DecisionMode.SHADOW,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
    )

    assert request.options == ("possible_duplicate", "validation_still_required")


def test_model_route_options_use_existing_hub_tiers():
    request = DecisionRequest.from_mapping(
        {"category": "model_route", "evidence_ids": ["ev-route"], "options": ["smart"]},
        decision_id="dec-route",
        mode=DecisionMode.ADVISORY,
        repository_id="repo-1",
        task_id="task-1",
        session_id="session-1",
    )

    assert request.options == ("smart",)


def test_non_success_result_requires_a_reason_code():
    request = DecisionRequest.from_mapping(
        {"category": "next_step", "evidence_ids": [], "options": ["inspect_source"]},
        decision_id="dec-4",
        mode=DecisionMode.SHADOW,
        repository_id="repo-1",
        task_id=None,
        session_id="session-4",
    )

    with pytest.raises(ValueError):
        DecisionResult.from_mapping(
            request,
            {"success": True, "status": "abstain", "suggestion": None, "reason_codes": []},
        )
