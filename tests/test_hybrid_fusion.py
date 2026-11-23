"""Tests for Tri-Hybrid Retrieval Fusion and Cross-Encoder Reranker."""

from src.local_ai_hub.hybrid_fusion import (
    classify_query_intent,
    reciprocal_rank_fusion,
)
from src.local_ai_hub.reranker_npu import CrossEncoderReranker


def test_classify_query_intent():
    code_q = "def handle_connection(socket: int) -> bool"
    code_intent = classify_query_intent(code_q)
    assert code_intent["ast"] > code_intent["dense"]

    concept_q = "how does authentication work across the whole architecture?"
    concept_intent = classify_query_intent(concept_q)
    assert concept_intent["dense"] > concept_intent["lexical"]


def test_reciprocal_rank_fusion():
    lex = ["file_a.py", "file_b.py", "file_c.py"]
    dense = ["file_b.py", "file_d.py", "file_a.py"]
    ast = ["file_b.py", "file_a.py", "file_e.py"]

    fused = reciprocal_rank_fusion(lex, dense, ast, k=10)
    # file_b.py is rank 2 in lex, rank 1 in dense, rank 1 in ast -> should be rank 1
    assert fused[0].doc_id == "file_b.py"
    assert "lexical" in fused[0].contributing_sources
    assert "dense" in fused[0].contributing_sources
    assert "ast" in fused[0].contributing_sources
    assert fused[0].rank == 1


def test_cross_encoder_reranker():
    reranker = CrossEncoderReranker()
    backend = reranker.initialize()
    assert backend

    docs = [
        ("doc1", "The quick brown fox jumps over the lazy dog."),
        ("doc2", "Authentication token verification and signature checks."),
        ("doc3", "Unrelated database connection pool configuration."),
    ]
    query = "Authentication token"
    results = reranker.rerank(query, docs, top_n=2)
    assert len(results) == 2
    assert results[0].doc_id == "doc2"
    assert results[0].relevance_score > results[1].relevance_score
