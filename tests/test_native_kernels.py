from __future__ import annotations

import array
import random
from types import SimpleNamespace

import pytest

from local_ai_hub import native_kernels
from local_ai_hub import rag


def test_validate_uint64_buffer_valid():
    buf = array.array("Q", [1, 2, 3, 2**64 - 1])
    validated = native_kernels._validate_uint64_buffer(buf)
    assert len(validated) == 4

    mv = memoryview(buf)
    validated_mv = native_kernels._validate_uint64_buffer(mv)
    assert len(validated_mv) == 4


def test_validate_uint64_buffer_rejects_invalid_types_and_dimensions():
    # Wrong array typecode
    with pytest.raises(TypeError, match="array typecode must be 'Q'"):
        native_kernels.simhash_votes(array.array("i", [1, 2, 3]))

    # Wrong object type
    with pytest.raises(TypeError, match="expected a buffer object"):
        native_kernels.simhash_votes([1, 2, 3])  # Python list is not a buffer

    # Multi-dimensional buffer
    try:
        import numpy as np
        arr_2d = np.array([[1, 2], [3, 4]], dtype=np.uint64)
        with pytest.raises(ValueError, match="expected 1D buffer"):
            native_kernels.simhash_votes(arr_2d)
    except ImportError:
        pass


def test_simhash_votes_empty_buffer():
    empty_buf = array.array("Q", [])
    assert native_kernels.simhash_votes(empty_buf) == 0


def test_simhash_votes_numerical_parity():
    rnd = random.Random(20261026)
    test_vectors = [
        [],
        [0],
        [2**64 - 1],
        [0, 2**64 - 1],
        [1, 2],
        [2**63] * 5,
    ]
    test_vectors += [[rnd.getrandbits(64) for _ in range(size)] for size in (1, 2, 10, 63, 64, 257)]

    for values in test_vectors:
        buf = array.array("Q", values)
        expected = native_kernels._python_simhash_votes(buf)
        actual = native_kernels.simhash_votes(buf)
        assert actual == expected


def test_simhash_text_parity_across_unicode_and_edge_cases():
    rnd = random.Random(20261026)
    texts = [
        "",
        " ",
        "\t\n  \r",
        "a",
        "abc",
        "abcd",
        " Žluťoučký\tKŮŇ\n pěl ďábelské ódy! ",
        "aaaa" * 512,
        "🙂漢字" * 15,
        "class CodeIndexer:\n    def __init__(self):\n        pass\n",
    ]
    texts += ["".join(rnd.choices("abCD ž漢🙂\t\n", k=size)) for size in (1, 3, 4, 16, 64, 512)]

    for text in texts:
        expected = rag._simhash(text)
        actual = native_kernels.simhash_text(text)
        assert actual == expected, f"Parity mismatch for text: {text!r}"


def test_native_enable_disable_toggle(monkeypatch):
    orig_enabled = native_kernels.is_native_enabled()
    try:
        native_kernels.set_native_enabled(False)
        assert native_kernels.is_native_enabled() is False

        # If a mock native module is present
        mock_module = SimpleNamespace(simhash_votes=lambda buf: 0xDEADBEEF)
        monkeypatch.setattr(native_kernels, "_NATIVE_SIMHASH_MODULE", mock_module)

        native_kernels.set_native_enabled(True)
        assert native_kernels.is_native_enabled() is True
        buf = array.array("Q", [1, 2, 3])
        assert native_kernels.simhash_votes(buf) == 0xDEADBEEF

        # Fallback when disabled
        native_kernels.set_native_enabled(False)
        assert native_kernels.simhash_votes(buf) == native_kernels._python_simhash_votes(buf)

        # Fallback on native exception
        def failing_native(buf):
            raise RuntimeError("simulated native kernel failure")

        mock_module.simhash_votes = failing_native
        native_kernels.set_native_enabled(True)
        # Should gracefully fall back to Python reference without raising
        assert native_kernels.simhash_votes(buf) == native_kernels._python_simhash_votes(buf)
    finally:
        native_kernels.set_native_enabled(orig_enabled)


def test_rag_simhash_graceful_delegation(monkeypatch):
    calls = []

    def mock_simhash_text(text):
        calls.append(text)
        return 0xCAFEBABE

    monkeypatch.setattr(native_kernels, "simhash_text", mock_simhash_text)
    monkeypatch.setattr(native_kernels, "is_native_enabled", lambda: True)

    result = rag._simhash("test string for delegation")
    assert result == 0xCAFEBABE
    assert calls == ["test string for delegation"]
