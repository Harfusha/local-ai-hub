import pytest

from local_ai_hub.laya_decisions import (
    ContextSourceEvidence,
    DecisionCategory,
    DecisionInput,
    DecisionMode,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
)


def test_decision_input_separates_typed_state_and_redacted_training_content():
    decision_input = DecisionInput.from_mapping(
        {
            "state": {"gap_code": "missing_verification"},
            "training_content": {
                "task_input": "Check this token=secret-value and missing receipt.",
                "context_excerpt": "No tool ran.",
            },
        }
    )

    assert decision_input.state == {"gap_code": "missing_verification"}
    assert decision_input.model_state() == {
        "gap_code": "missing_verification",
        "raw_task_input": "Check this token=[REDACTED] and missing receipt.",
        "raw_context_excerpt": "No tool ran.",
        "training_redacted_fields": "task_input",
        "training_missing_fields": "none",
        "training_missing_reason": "none",
    }
    assert decision_input.redacted_fields == ("task_input",)


def test_decision_input_redacts_email_and_private_key_material():
    decision_input = DecisionInput.from_mapping(
        {
            "state": {"gap_code": "unresolved_evidence_gap"},
            "training_content": {
                "task_input": "Contact alice@example.com with this key:",
                "context_excerpt": (
                    "-----BEGIN PRIVATE KEY-----\\n"
                    "private-key-material\\n"
                    "-----END PRIVATE KEY-----"
                ),
            },
        }
    )

    model_state = decision_input.model_state()
    assert model_state["raw_task_input"] == "Contact [REDACTED] with this key:"
    assert model_state["raw_context_excerpt"] == "[REDACTED]"
    assert model_state["training_redacted_fields"] == "context_excerpt,task_input"
    assert model_state["training_missing_fields"] == "none"
    assert model_state["training_missing_reason"] == "none"
    assert decision_input.redacted_fields == ("task_input", "context_excerpt")


def test_decision_input_marks_missing_raw_training_fields():
    decision_input = DecisionInput.from_mapping(
        {"state": {"complexity": "heavy"}, "training_content": {"task_input": "Inspect parser."}}
    )

    assert decision_input.model_state() == {
        "complexity": "heavy",
        "raw_task_input": "Inspect parser.",
        "training_redacted_fields": "none",
        "training_missing_fields": "context_excerpt",
        "training_missing_reason": "context_excerpt_unavailable",
    }


def test_decision_input_redacts_model_and_tool_outputs_for_general_decisions():
    decision_input = DecisionInput.from_mapping(
        {
            "state": {"task_type": "code"},
            "training_content": {
                "task_input": "Inspect parser.",
                "model_response": "Authorization: Bearer abc.def",
                "tool_output_excerpt": "token=secret-value",
            },
        }
    )

    assert decision_input.model_state()["raw_model_response"] == "Authorization: [REDACTED]"
    assert decision_input.model_state()["raw_tool_output_excerpt"] == "token=[REDACTED]"
    assert decision_input.redacted_fields == ("model_response", "tool_output_excerpt")
    assert decision_input.model_state()["training_redacted_fields"] == "model_response,tool_output_excerpt"


def test_context_source_rejects_model_and_tool_output_training_content():
    with pytest.raises(ValueError, match="context source training content fields invalid"):
        ContextSourceEvidence.from_mapping(
            {
                "gap_code": "unresolved_evidence_gap",
                "source_codes": ["indexed", "artifact"],
                "freshness_codes": ["current", "current"],
                "coverage_codes": ["complete", "complete"],
                "evidence_ids": ["ev-1", "ev-2"],
                "training_content": {"model_response": "irrelevant"},
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"state": {"nested": {"text": "x"}}, "training_content": {}},
        {"state": {}, "training_content": {"conversation": "not allowed"}},
        {"state": {"raw_text": "not typed"}, "training_content": {}},
        {"state": {"raw_task_input": "spoofed"}, "training_content": {}},
    ],
)
def test_decision_input_rejects_unbounded_or_aliased_content(payload):
    with pytest.raises(ValueError):
        DecisionInput.from_mapping(payload)


def test_context_source_evidence_accepts_redacted_training_content_separately():
    context = ContextSourceEvidence.from_mapping(
        {
            "gap_code": "unresolved_evidence_gap",
            "source_codes": ["indexed", "artifact", "memory"],
            "freshness_codes": ["current", "current", "stale"],
            "coverage_codes": ["complete", "complete", "complete"],
            "evidence_ids": ["ev-1", "ev-2", "ev-3"],
            "training_content": {
                "task_input": "Find the parser for token=secret-value.",
                "context_excerpt": "parser.py: parse_request validates input.",
            },
        },
    )

    assert context.decision_options == ("indexed", "artifact", "memory")
    assert context.model_input() == {
        "gap_code": "unresolved_evidence_gap",
        "source_codes": ["indexed", "artifact", "memory"],
        "freshness_codes": ["current", "current", "stale"],
        "coverage_codes": ["complete", "complete", "complete"],
        "evidence_ids": ["ev-1", "ev-2", "ev-3"],
        "raw_task_input": "Find the parser for token=[REDACTED]",
        "raw_context_excerpt": "parser.py: parse_request validates input.",
        "training_redacted_fields": "task_input",
        "training_missing_fields": "none",
        "training_missing_reason": "none",
    }
    assert context.redacted_fields == ("task_input",)


def test_context_source_training_content_limits_are_measured_in_utf8_bytes():
    payload = {
        "gap_code": "unresolved_evidence_gap",
        "source_codes": ["indexed", "artifact"],
        "freshness_codes": ["current", "current"],
        "coverage_codes": ["partial", "complete"],
        "evidence_ids": ["ev-1", "ev-2"],
        "training_content": {"task_input": "é" * 4096},
    }

    ContextSourceEvidence.from_mapping(payload)
    payload["training_content"]["task_input"] += "é"
    with pytest.raises(ValueError, match="too large"):
        ContextSourceEvidence.from_mapping(payload)


@pytest.mark.parametrize(
    "override",
    [
        {"prompt": "private text"},
        {"gap_code": "please read this source"},
        {"source_codes": ["private source text", "artifact"]},
        {"freshness_codes": ["recent-ish", "current"]},
        {"coverage_codes": ["complete", "almost-complete"]},
        {"coverage_codes": ["complete"]},
        {"source_codes": ["indexed", "indexed"]},
        {"evidence_ids": ["ev-1", "ev-1"]},
    ],
)
def test_context_source_evidence_rejects_free_text_aliases_and_invalid_codes(override):
    payload = {
        "gap_code": "unresolved_evidence_gap",
        "source_codes": ["indexed", "artifact", "memory"],
        "freshness_codes": ["current", "stale", "unknown"],
        "coverage_codes": ["complete", "complete", "incomplete"],
        "evidence_ids": ["ev-1", "ev-2", "ev-3"],
        "training_content": {},
    }
    payload.update(override)

    with pytest.raises(ValueError):
        ContextSourceEvidence.from_mapping(payload)


def test_context_source_evidence_retains_bad_source_codes_for_false_positive_measurement():
    context = ContextSourceEvidence.from_mapping(
        {
            "gap_code": "unresolved_evidence_gap",
            "source_codes": ["indexed", "artifact", "memory"],
            "freshness_codes": ["current", "stale", "current"],
            "coverage_codes": ["complete", "complete", "partial"],
            "evidence_ids": ["ev-1", "ev-2", "ev-3"],
        },
    )

    assert context.decision_options == ("indexed", "artifact", "memory")


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
