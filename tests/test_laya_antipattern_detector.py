import pytest
from src.local_ai_hub.laya_antipattern_detector import LayaAntiPatternDetector


def test_antipattern_detection_clean_code():
    detector = LayaAntiPatternDetector()

    clean_code = """
def compute_sum(a: int, b: int) -> int:
    try:
        return a + b
    except TypeError as exc:
        logger.error("Type error in sum: %s", exc)
        return 0
"""
    res = detector.scan_code(clean_code)
    assert res.has_violations is False
    assert res.status == "clean"
    assert res.risk_score == 0.0


def test_antipattern_detection_violations():
    detector = LayaAntiPatternDetector()

    # 1. Critical signed char array initialization
    bad_array_code = "arr = array.array('b', raw_bytes)"
    res1 = detector.scan_code(bad_array_code)
    assert res1.has_violations is True
    assert res1.status == "rejected"
    assert any(v.pattern_id == "signed_char_array_overflow" for v in res1.violations)

    # 2. Critical destructive git reset
    bad_git = "run_command('git reset --hard HEAD')"
    res2 = detector.scan_code(bad_git)
    assert res2.has_violations is True
    assert res2.status == "rejected"
    assert any(v.pattern_id == "destructive_git_command" for v in res2.violations)

    # 3. Warning silent exception swallow
    bad_except = """
try:
    do_something()
except:
    pass
"""
    res3 = detector.scan_code(bad_except)
    assert res3.has_violations is True
    assert res3.status == "warning"
    assert any(v.pattern_id == "silent_exception_swallow" for v in res3.violations)
