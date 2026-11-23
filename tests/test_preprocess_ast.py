"""Tests for AST symbol-level granular chunking."""

from src.local_ai_hub.preprocess_ast import (
    AstSymbolChunk,
    diff_ast_symbols,
    enrich_card_with_ast_symbols,
    extract_ast_symbol_chunks,
)


def test_extract_python_symbols():
    code = '''
class ServiceWorker:
    def __init__(self, name: str):
        self.name = name

    def execute(self) -> bool:
        return True

def standalone_task(x: int) -> int:
    return x * 2
'''
    chunks = extract_ast_symbol_chunks("test_service.py", code)
    names = [c.name for c in chunks]
    assert "ServiceWorker" in names
    assert "ServiceWorker.__init__" in names
    assert "ServiceWorker.execute" in names
    assert "standalone_task" in names

    assert all(c.body_sha256 for c in chunks)


def test_diff_ast_symbols_and_reuse():
    code_v1 = '''
def func_a():
    return 1

def func_b():
    return 2
'''
    code_v2 = '''
def func_a():
    return 1

def func_b():
    # modified!
    return 999
'''
    chunks_v1 = extract_ast_symbol_chunks("module.py", code_v1)
    chunks_v2 = extract_ast_symbol_chunks("module.py", code_v2)

    diff = diff_ast_symbols(chunks_v1, chunks_v2)
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].name == "func_a"
    assert len(diff.modified) == 1
    assert diff.modified[0][1].name == "func_b"
    assert diff.reuse_ratio == 0.5


def test_enrich_card_with_ast_symbols():
    code = "def process(): pass"
    chunks = extract_ast_symbol_chunks("proc.py", code)
    base_card = {"purpose": "testing", "symbols": []}
    enriched = enrich_card_with_ast_symbols(base_card, chunks)
    assert "process" in enriched["symbols"]
    assert "ast_symbol_chunks" in enriched
    assert len(enriched["ast_symbol_chunks"]) == 1
