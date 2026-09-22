from local_ai_hub.semantic_quality import assess_semantic_result
from local_ai_hub.services import LocalAIServices


def test_unrelated_paths_are_rejected_as_advisory_only():
    result = assess_semantic_result(
        task="diagnose src/auth.py",
        evidence_paths=["src/auth.py"],
        output="Fix src/Calculator.java and src/UserManager.java",
    )

    assert result["usable"] is False
    assert result["reason"] == "unrelated_output"
    assert result["advisory_only"] is True
    assert result["bypass_reason"] == "unrelated_output"


def test_queued_model_result_requests_bypass():
    result = assess_semantic_result("review diff", ["src/a.py"], "queued")

    assert result["usable"] is False
    assert result["reason"] == "queued"
    assert result["advisory_only"] is True


def test_empty_model_result_requests_bypass():
    result = assess_semantic_result("review diff", ["src/a.py"], "  \n")

    assert result["usable"] is False
    assert result["reason"] == "empty_output"


def test_generic_model_output_is_flagged_without_auto_rejection():
    result = assess_semantic_result(
        task="diagnose adapter readback",
        evidence_paths=["src/adapter.py"],
        output="This indicates a potential mismatch between hardware or software.",
    )

    assert result["usable"] is False
    assert result["reason"] == "generic_output"
    assert result["advisory_only"] is True


def test_explicit_model_error_is_rejected():
    result = assess_semantic_result("review diff", ["src/a.py"], "ERROR: model unavailable")

    assert result["usable"] is False
    assert result["reason"] == "model_error"


def test_non_string_output_is_malformed():
    result = assess_semantic_result("review diff", ["src/a.py"], {"answer": "ok"})

    assert result["usable"] is False
    assert result["reason"] == "malformed_output"


def test_structured_queued_output_is_rejected():
    result = assess_semantic_result("review diff", ["src/a.py"], {"status": "queued"})

    assert result["usable"] is False
    assert result["reason"] == "queued"


def test_output_and_paths_are_bounded():
    too_many_paths = [f"src/file_{index}.py" for index in range(65)]
    result = assess_semantic_result("review diff", too_many_paths, "ok")

    assert result["usable"] is False
    assert result["reason"] == "paths_too_many"

    result = assess_semantic_result("review diff", ["src/" + "x" * 300], "ok")
    assert result["usable"] is False
    assert result["reason"] == "path_too_long"

    result = assess_semantic_result("review diff", ["src/a.py"], "x" * 12001)
    assert result["usable"] is False
    assert result["reason"] == "output_too_large"


def test_unsafe_and_malformed_evidence_paths_are_rejected():
    result = assess_semantic_result("review diff", ["../outside.py"], "ok")
    assert result["usable"] is False
    assert result["reason"] == "unsafe_path"

    result = assess_semantic_result("review diff", [42], "ok")
    assert result["usable"] is False
    assert result["reason"] == "malformed_paths"


def test_unrelated_absolute_path_is_not_silently_accepted():
    result = assess_semantic_result(
        "review diff",
        ["src/auth.py"],
        r"Fix C:\other\Calculator.java",
    )
    assert result["usable"] is False
    assert result["reason"] == "unrelated_output"


def test_matching_path_is_usable_but_still_advisory():
    result = assess_semantic_result(
        "diagnose src/auth.py",
        ["src/auth.py"],
        "Inspect src\\auth.py:42 and update the validation branch.",
    )

    assert result["usable"] is True
    assert result["reason"] is None
    assert result["advisory_only"] is True
    assert result["bypass_reason"] is None


def test_detached_line_claim_is_rejected_as_unverified_location():
    result = assess_semantic_result(
        "review diff",
        ["src/auth.py"],
        "The issue is in src/auth.py at line 456.",
    )

    assert result["usable"] is False
    assert result["reason"] == "unsupported_location"


def test_human_line_label_is_allowed_when_qualified_location_is_also_present():
    result = assess_semantic_result(
        "review diff",
        ["tests/test_demo.py"],
        "Path:tests/test_demo.py line 4; exact location tests/test_demo.py:4.",
    )

    assert result["usable"] is True


def test_pathless_analysis_is_usable():
    result = assess_semantic_result("summarize evidence", ["src/auth.py"], "The branch handles missing tokens.")

    assert result["usable"] is True
    assert result["advisory_only"] is True


def test_service_quality_gate_keeps_unrelated_model_result_visible_as_advisory():
    result = LocalAIServices._apply_semantic_quality(
        {"success": True, "text": "Fix src/Calculator.java"},
        task="diagnose src/auth.py",
        evidence_paths=["src/auth.py"],
    )
    assert result["success"] is True
    assert result["advisory_only"] is True
    assert result["bypass_reason"] == "unrelated_output"
    assert result["semantic_quality"]["usable"] is False
    assert "quality_warning" in result
