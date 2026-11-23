"""Unit tests for HNSW In-Memory Vector Index."""

import random
from local_ai_hub.hnsw_index import HNSWIndex


def test_hnsw_insert_and_exact_recall() -> None:
    dim = 64
    index = HNSWIndex(dim=dim, m=8, ef_construction=16, ef_search=16)

    random.seed(42)
    # Generate 30 vectors
    vectors = {}
    for i in range(30):
        doc_id = f"doc_{i}"
        vec = [random.uniform(-1, 1) for _ in range(dim)]
        vectors[doc_id] = vec
        index.insert(doc_id, vec)

    assert index.size() == 30

    # Query with exact vector of doc_7
    query = vectors["doc_7"]
    results = index.search(query, top_k=3)
    assert len(results) >= 1
    # Top result must be doc_7 with similarity near 1.0
    top_doc, top_score = results[0]
    assert top_doc == "doc_7"
    assert top_score > 0.99


def test_hnsw_empty_index() -> None:
    index = HNSWIndex(dim=32)
    assert index.size() == 0
    assert index.search([0.1] * 32) == []
