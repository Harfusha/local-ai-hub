import pytest
from src.local_ai_hub.laya_code_scorer import LayaCodeScorer


def test_code_scorer_clean_code():
    scorer = LayaCodeScorer()

    clean_code = '''
def add_vectors(a: list[float], b: list[float]) -> list[float]:
    """Add two equal-length vectors element-wise."""
    if len(a) != len(b):
        raise ValueError("Vector lengths must match")
    return [x + y for x, y in zip(a, b)]
'''
    score = scorer.score_code(clean_code)

    assert score.overall_score > 0.8
    assert score.maintainability_index > 50.0
    assert score.type_coverage_percent == 100.0
    assert score.has_docstrings is True
    assert score.cyclomatic_complexity in (2, 3)
    assert len(score.recommendations) == 0


def test_code_scorer_untyped_complex_code():
    scorer = LayaCodeScorer()

    messy_code = '''
def complex_fn(a, b, c, d, e):
    if a:
        if b:
            for x in c:
                if x > 0:
                    while d:
                        if e:
                            return 1
                        else:
                            return 2
    return 0
'''
    score = scorer.score_code(messy_code)

    assert score.overall_score < 0.6
    assert score.type_coverage_percent == 0.0
    assert score.cyclomatic_complexity >= 6
    assert any("type annotations" in r for r in score.recommendations)
