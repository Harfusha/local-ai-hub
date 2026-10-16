import pytest
from local_ai_hub.model_quality import (
    evaluate_case,
    quality_floor_failures,
    promote_candidate,
    CandidateRegistry,
    REJECTED,
)


def test_evaluate_case_hardening():
    # evidence_paths as None or bool should not raise TypeError
    res_none = evaluate_case("task", None, {"path": "a.py"}, {})
    assert isinstance(res_none, dict)
    assert "hallucinated_paths" in res_none

    res_bool = evaluate_case("task", True, {"path": "a.py"}, {})
    assert isinstance(res_bool, dict)

    # evidence_paths as string should not be split character by character
    res_str = evaluate_case("task", "src/foo.py", {"path": "src/foo.py"}, {})
    assert res_str["hallucinated_paths"] == []


def test_quality_floor_failures_hardening():
    # metrics as None or bool should safely return failure keys without AttributeError
    failures_none = quality_floor_failures(None)
    assert len(failures_none) > 0

    failures_bool = quality_floor_failures(True, quality_floor=True)
    assert len(failures_bool) > 0


def test_candidate_promotion_and_registry_hardening():
    # Non-mapping candidate
    res_invalid = promote_candidate(True)
    assert res_invalid["status"] == REJECTED

    # Registry with boolean quality_floor
    reg = CandidateRegistry(quality_floor=True)
    assert reg.quality_floor
    assert reg.get("nonexistent") is None
