"""Unit tests for AST Type Annotation Synthesizer."""

from local_ai_hub.type_synthesizer import synthesize_types


def test_synthesize_return_types() -> None:
    code = """def get_status():
    return "active"

def compute_total(a, b):
    return 100

def is_ready():
    return True

def do_nothing():
    pass
"""
    res = synthesize_types(code)
    assert res.synthesized_count >= 4
    assert "def get_status() -> str:" in res.enriched_code
    assert "def compute_total(a, b) -> int:" in res.enriched_code
    assert "def is_ready() -> bool:" in res.enriched_code
    assert "def do_nothing() -> None:" in res.enriched_code


def test_synthesize_argument_types_from_defaults() -> None:
    code = """def connect(host, port=8080, timeout=5.0, use_ssl=True):
    return True
"""
    res = synthesize_types(code)
    assert res.synthesized_count >= 4
    assert "port: int=8080" in res.enriched_code
    assert "timeout: float=5.0" in res.enriched_code
    assert "use_ssl: bool=True" in res.enriched_code
    assert "-> bool:" in res.enriched_code
