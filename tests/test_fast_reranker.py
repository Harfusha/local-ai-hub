"""Unit tests for Fast Multi-Signal Reciprocal Rank Fusion Reranker."""

from local_ai_hub.fast_reranker import FastRRFReranker


def test_rrf_reranking_fusion() -> None:
    reranker = FastRRFReranker(k=60.0)

    # BM25 found: [doc_A, doc_B, doc_C]
    # Dense vector found: [doc_B, doc_A, doc_D]
    # Graph found: [doc_B, doc_E]
    channels = {
        "bm25": ["doc_A", "doc_B", "doc_C"],
        "dense": ["doc_B", "doc_A", "doc_D"],
        "graph": ["doc_B", "doc_E"],
    }

    # doc_B is rank 2 in bm25, rank 1 in dense, rank 1 in graph -> should be #1 overall
    results = reranker.rerank(channels, top_k=3)
    assert len(results) == 3
    assert results[0].doc_id == "doc_B"
    assert "bm25" in results[0].contributing_channels
    assert "dense" in results[0].contributing_channels
    assert "graph" in results[0].contributing_channels
    assert results[0].channel_ranks["dense"] == 1

    # doc_A is rank 1 in bm25, rank 2 in dense -> should be #2 overall
    assert results[1].doc_id == "doc_A"


def test_rrf_channel_weighting() -> None:
    reranker = FastRRFReranker(k=60.0)

    channels = {
        "bm25": ["doc_exact"],
        "dense": ["doc_semantic"],
    }
    # With higher weight on BM25, doc_exact wins
    res_bm25_heavy = reranker.rerank(channels, channel_weights={"bm25": 2.0, "dense": 1.0})
    assert res_bm25_heavy[0].doc_id == "doc_exact"

    # With higher weight on Dense, doc_semantic wins
    res_dense_heavy = reranker.rerank(channels, channel_weights={"bm25": 1.0, "dense": 3.0})
    assert res_dense_heavy[0].doc_id == "doc_semantic"
