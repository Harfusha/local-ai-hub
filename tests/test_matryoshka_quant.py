"""Unit tests for Matryoshka Embeddings & Int8 Scalar Quantization."""

import math
import random
from local_ai_hub.matryoshka_quant import (
    Int8VectorIndex,
    asymmetric_dot_product,
    dequantize_int8,
    quantize_int8,
    truncate_matryoshka,
)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-12)


def test_matryoshka_truncation_normalization() -> None:
    vec = [random.uniform(-1, 1) for _ in range(768)]
    trunc = truncate_matryoshka(vec, target_dim=256)
    assert len(trunc) == 256
    norm = math.sqrt(sum(x * x for x in trunc))
    assert abs(norm - 1.0) < 1e-5


def test_int8_quantize_dequantize_fidelity() -> None:
    vec = [random.uniform(-1, 1) for _ in range(256)]
    # Normalize
    n = math.sqrt(sum(x * x for x in vec))
    vec = [x / n for x in vec]

    q_bytes, scale = quantize_int8(vec)
    assert len(q_bytes) == 256
    recon = dequantize_int8(q_bytes, scale)

    # Reconstructed vector should have >0.99 cosine similarity to original
    sim = _cosine_similarity(vec, recon)
    assert sim > 0.99


def test_asymmetric_dot_product_accuracy() -> None:
    q = [random.uniform(-1, 1) for _ in range(256)]
    target = [random.uniform(-1, 1) for _ in range(256)]

    # Exact float dot product
    exact_dot = sum(x * y for x, y in zip(q, target))

    # Asymmetric dot product
    q_bytes, scale = quantize_int8(target)
    adc_dot = asymmetric_dot_product(q, q_bytes, scale)

    # Error should be within 1% of magnitude
    assert abs(exact_dot - adc_dot) < 0.05 * (abs(exact_dot) + 1.0)


def test_int8_vector_index_search() -> None:
    index = Int8VectorIndex(target_dim=256)

    # Add 20 mock documents
    random.seed(42)
    doc_vectors = {}
    for i in range(20):
        vec = [random.uniform(-1, 1) for _ in range(768)]
        doc_id = f"doc_{i}"
        doc_vectors[doc_id] = vec
        index.add(doc_id, vec)

    assert index.size() == 20
    # 20 docs * (256 bytes + 8 bytes) = 5280 bytes (4x smaller than float32)
    assert index.byte_size() == 20 * 264

    # Search with doc_5 as query
    results = index.search(doc_vectors["doc_5"], top_k=3)
    assert len(results) == 3
    # Top result should be doc_5 itself
    assert results[0].doc_id == "doc_5"
    assert results[0].score > 0.95
