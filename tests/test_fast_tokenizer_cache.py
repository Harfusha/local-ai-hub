"""Unit tests for Fast Tokenizer Segment Cache."""

import time
from local_ai_hub.fast_tokenizer_cache import FastTokenizerCache


def test_tokenizer_cache_store_and_retrieve() -> None:
    cache = FastTokenizerCache(max_cached_tokens=1000)

    text = "def calculate_hash(data: bytes) -> str:"
    tokens = [120, 4590, 89, 3120, 10, 44]

    # Store
    count = cache.store_tokens(text, tokens)
    assert count == len(tokens)

    # Retrieve list
    retrieved = cache.get_tokens(text)
    assert retrieved == tokens

    # Retrieve zero-copy view
    view = cache.get_tokens_view(text)
    assert view is not None
    assert list(view) == tokens

    # Miss on new text
    assert cache.get_tokens("completely new text") is None

    stats = cache.stats()
    assert stats["cached_segments"] == 1
    assert stats["total_tokens_cached"] == len(tokens)
    assert stats["hits"] == 2
    assert stats["misses"] == 1


def test_tokenizer_cache_lru_eviction() -> None:
    # Small budget: 10 tokens
    cache = FastTokenizerCache(max_cached_tokens=10)

    cache.store_tokens("t1", [1, 2, 3, 4, 5])
    time.sleep(0.01)
    cache.store_tokens("t2", [6, 7, 8, 9, 10])
    time.sleep(0.01)

    # Adding t3 (5 tokens) should evict oldest (t1)
    cache.store_tokens("t3", [11, 12, 13, 14, 15])

    assert cache.get_tokens("t1") is None
    assert cache.get_tokens("t2") is not None
    assert cache.get_tokens("t3") is not None
