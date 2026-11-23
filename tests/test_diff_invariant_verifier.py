"""Unit tests for Source Diff Invariant Verifier."""

from local_ai_hub.diff_invariant_verifier import verify_code_invariants


def test_verify_syntax_and_patterns() -> None:
    # 1. Invalid syntax
    bad_syntax = "def broken(x: return x"
    verdict_syntax = verify_code_invariants(bad_syntax)
    assert not verdict_syntax.passed
    assert any("Syntax error" in v for v in verdict_syntax.violations)

    # 2. Dangerous bare except pass
    bad_pattern = """
def test_fn():
    try:
        do_something()
    except:
        pass
"""
    verdict_pat = verify_code_invariants(bad_pattern)
    assert not verdict_pat.passed
    assert any("Bare 'except: pass'" in v for v in verdict_pat.violations)


def test_interface_preservation_and_nesting() -> None:
    base = """
def process_data(data, options):
    return len(data)

class DataProcessor:
    pass
"""
    # Candidate deleted DataProcessor and reduced process_data arguments
    candidate_bad = """
def process_data(data):
    return len(data)
"""
    verdict = verify_code_invariants(candidate_bad, base_code=base)
    assert not verdict.passed
    assert not verdict.public_interfaces_preserved
    assert any("deleted" in v for v in verdict.violations)
    assert any("reduced arguments" in v for v in verdict.violations)

    # Candidate with valid additions
    candidate_good = """
def process_data(data, options, extra=None):
    return len(data)

class DataProcessor:
    pass

def new_feature():
    return 42
"""
    verdict_good = verify_code_invariants(candidate_good, base_code=base)
    assert verdict_good.passed
    assert verdict_good.public_interfaces_preserved
    assert len(verdict_good.violations) == 0
