"""Unit tests for Speculative Critique Verifier."""

from local_ai_hub.speculative_critique import critique_code


def test_critique_clean_code_accept() -> None:
    code = """def process_items(items: list[int]) -> int:
    with open("log.txt", "w") as f:
        f.write("started")
    return sum(items)
"""
    verdict = critique_code(code)
    assert verdict.decision == "ACCEPT"
    assert verdict.score >= 0.90
    assert len(verdict.warnings) == 0


def test_critique_raw_open_refine() -> None:
    code = """def leaky():
    f = open("leak.txt", "w")
    f.write("bad")
    return 1
"""
    verdict = critique_code(code)
    assert verdict.decision in ("REFINE", "REJECT")
    assert any("open()" in w for w in verdict.warnings)
    assert any("with open" in r for r in verdict.suggested_refinements)
