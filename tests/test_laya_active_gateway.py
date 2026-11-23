import pytest
from src.local_ai_hub.laya_active_gateway import (
    LayaActiveGateway,
    RetrievalStrategy,
    ModelTier,
    ContextAction,
)


def test_laya_retrieval_routing():
    gateway = LayaActiveGateway(mode="advisory")

    # 1. Exact symbol query
    rec_symbol = gateway.route_retrieval("def calculate_fibonacci")
    assert rec_symbol.strategy == RetrievalStrategy.AST_SYMBOL
    assert "semantic_hnsw" in rec_symbol.skip_branches
    assert rec_symbol.estimated_latency_saved_ms > 0

    # 2. Error stack trace
    rec_err = gateway.route_retrieval("Traceback (most recent call last): File 'main.py', line 42")
    assert rec_err.strategy == RetrievalStrategy.LEXICAL_BM25
    assert "graphrag" in rec_err.skip_branches

    # 3. Architecture query
    rec_arch = gateway.route_retrieval("Explain overall subsystem component hierarchy")
    assert rec_arch.strategy == RetrievalStrategy.GRAPHRAG
    assert "ast_symbol" in rec_arch.skip_branches

    # 4. Pure natural language conceptual question
    rec_sem = gateway.route_retrieval("how does the memory management clean up old sessions without errors")
    assert rec_sem.strategy == RetrievalStrategy.SEMANTIC_HNSW


def test_laya_model_routing_and_pruning():
    gateway = LayaActiveGateway(mode="advisory")

    # Fast tier
    fast_rec = gateway.route_model("add type annotation to helper function", context_token_count=1200)
    assert fast_rec.tier == ModelTier.FAST
    assert fast_rec.model_name == "qwen2.5-coder:1.5b"
    assert fast_rec.speculative_window == 6

    # Reasoning tier
    reason_rec = gateway.route_model("design architecture for distributed consensus protocol", context_token_count=10000)
    assert reason_rec.tier == ModelTier.REASONING
    assert reason_rec.model_name == "qwen3.5:9b"

    # Context pruning
    files = ["src/core/engine.py", "tests/test_unrelated.py", "src/auth/tokens.py"]
    actions = gateway.evaluate_context_pruning(files, query="engine calculation")
    assert actions["src/core/engine.py"] == ContextAction.KEEP_FULL
    assert actions["tests/test_unrelated.py"] == ContextAction.DROP


def test_laya_pre_verification():
    gateway = LayaActiveGateway(mode="advisory")

    # Valid diff
    valid_res = gateway.pre_verify_output("def foo(x: int) -> int:\n    return x + 1\n")
    assert valid_res.passed is True
    assert valid_res.recommended_action == "proceed_to_test_suite"

    # Unsafe diff with eval
    unsafe_res = gateway.pre_verify_output("def run_dyn(code: str):\n    eval(code)\n")
    assert unsafe_res.passed is False
    assert any("eval()" in f for f in unsafe_res.findings)

    # Corrupted brackets
    corrupt_res = gateway.pre_verify_output("def foo(x):\n    return [x, (x+1)\n")
    assert corrupt_res.passed is False
    assert any("Mismatched bracket count" in f for f in corrupt_res.findings)
