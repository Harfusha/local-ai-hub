from __future__ import annotations

from local_ai_hub.client_adapters.prompt_cache_shield import (
    normalize_for_prompt_cache,
)


def test_prompt_cache_shield_sorts_keys():
    unordered = {
        "z": 1,
        "a": 2,
        "m": {"zebra": 10, "apple": 20},
        "items": [{"b": 1, "a": 2}, 3.14159265],
    }
    normalized = normalize_for_prompt_cache(unordered)
    keys = list(normalized.keys())
    assert keys == ["a", "items", "m", "z"]
    assert list(normalized["m"].keys()) == ["apple", "zebra"]
    assert list(normalized["items"][0].keys()) == ["a", "b"]
    assert normalized["items"][1] == 3.141593


def test_prompt_cache_shield_handles_primitives():
    assert normalize_for_prompt_cache("text") == "text"
    assert normalize_for_prompt_cache(42) == 42
    assert normalize_for_prompt_cache(None) is None
    assert normalize_for_prompt_cache([3, 2, 1]) == [3, 2, 1]
