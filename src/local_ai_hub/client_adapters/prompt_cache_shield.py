"""PromptCacheShield — deterministic normalization for KV prompt caching.

Ensures dictionary keys are stably sorted and float values rounded
to minimize prompt cache invalidations on modern providers (Claude / OpenAI / Gemini).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalize_for_prompt_cache(val: Any) -> Any:
    """Recursively sort dictionary keys and normalize structures for stable hashing."""
    if isinstance(val, Mapping):
        return {str(k): normalize_for_prompt_cache(val[k]) for k in sorted(val.keys())}
    if isinstance(val, (list, tuple)):
        return [normalize_for_prompt_cache(x) for x in val]
    if isinstance(val, float):
        return round(val, 6)
    return val
