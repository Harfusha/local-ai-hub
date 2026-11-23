"""Unit tests for SIMD / AVX2 Chunked Vector Kernel."""

import array
import random
from local_ai_hub.simd_vector_kernel import (
    simd_batch_dot_product,
    simd_dot_int8,
    simd_top_k,
)


def test_simd_dot_int8_precision() -> None:
    dim = 256
    random.seed(42)
    q = [random.uniform(-1, 1) for _ in range(dim)]
    int8_vals = [random.randint(-127, 127) for _ in range(dim)]
    target_bytes = array.array("b", int8_vals).tobytes()
    scale = 0.005

    # Analytical sum
    expected = sum(q[i] * int8_vals[i] for i in range(dim)) * scale

    # SIMD chunked sum
    result = simd_dot_int8(q, target_bytes, scale)

    assert abs(expected - result) < 1e-6


def test_simd_batch_dot_product() -> None:
    dim = 256
    num_docs = 50
    random.seed(123)

    q = [random.uniform(-1, 1) for _ in range(dim)]
    scales = [0.002 * (i + 1) for i in range(num_docs)]
    doc_ids = [f"doc_{i}" for i in range(num_docs)]

    all_bytes = bytearray()
    for _ in range(num_docs):
        vals = [random.randint(-127, 127) for _ in range(dim)]
        all_bytes.extend(array.array("b", vals).tobytes())

    scores = simd_batch_dot_product(q, bytes(all_bytes), scales, dim)
    assert len(scores) == num_docs

    # Check top_k extraction
    top3 = simd_top_k(q, bytes(all_bytes), scales, doc_ids, dim, top_k=3)
    assert len(top3) == 3
    # Check sorted descending
    assert top3[0][1] >= top3[1][1] >= top3[2][1]
    # Top score matches max of scores
    assert abs(top3[0][1] - max(scores)) < 1e-6
