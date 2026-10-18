import pytest
from pathlib import Path
from local_ai_hub.planner import AdaptivePlanner, _safe_int, _safe_float
from local_ai_hub.speculative_lint import (
    normalize_changed_paths,
    SpeculativeLintQueue,
    _safe_int as lint_safe_int,
    _safe_float as lint_safe_float,
)


def test_planner_safe_int_and_float_overflow():
    # OverflowError with float infinity must be handled safely
    assert _safe_int(float("inf"), 4) == 4
    assert _safe_int(float("-inf"), 4) == 4
    assert _safe_int("not-an-int", 4) == 4
    assert _safe_int(True, 4) == 4
    assert _safe_int(None, 4) == 4

    assert _safe_float(float("inf"), 0.5) == 0.5
    assert _safe_float(float("-inf"), 0.5) == 0.5
    assert _safe_float(True, 0.5) == 0.5
    assert _safe_float(None, 0.5) == 0.5


def test_planner_plan_confidence_rounding_and_overflow(tmp_path):
    # Disabled planner and quality mode should have rounded confidence
    planner_disabled = AdaptivePlanner(config={"execution_planner": {"enabled": False}})
    plan = planner_disabled.plan({}, 0, {"confidence": 0.333333333}, 1)
    assert plan["confidence"] == round(plan["confidence"], 4)

    planner_quality = AdaptivePlanner()
    plan_q = planner_quality.plan({}, 0, {"confidence": 0.333333333}, 1, mode="quality")
    assert plan_q["confidence"] == round(plan_q["confidence"], 4)

    # Infinite evidence count must not crash with OverflowError
    plan_inf = planner_quality.plan({}, 0, {"confidence": 0.5}, float("inf"))
    assert isinstance(plan_inf["confidence"], float)


def test_speculative_lint_normalize_changed_paths_booleans_and_types(tmp_path):
    f1 = tmp_path / "foo.py"
    f1.write_text("print(1)")

    # Root must not accept booleans
    with pytest.raises(ValueError):
        normalize_changed_paths(True, ["foo.py"])

    # Paths containing booleans or non-paths must not resolve boolean as file "True"
    with pytest.raises(ValueError):
        normalize_changed_paths(tmp_path, [True, False])

    # Valid path with booleans filtered out or rejected
    res = normalize_changed_paths(tmp_path, [True, "foo.py", False, 123])
    assert res == ["foo.py"]


def test_speculative_lint_queue_submit_root_guards():
    queue = SpeculativeLintQueue(None, {"speculative_lint": {"enabled": True}})
    # Boolean root
    res_bool = queue.submit(True, ["foo.py"])
    assert res_bool["success"] is False
    assert "root" in res_bool.get("error", "").lower()

    # Null byte root
    res_null = queue.submit("bad\x00root", ["foo.py"])
    assert res_null["success"] is False
