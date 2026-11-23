"""Tests for Prompt Prefix Cache Manager and VRAM Defragmentation."""

from src.local_ai_hub.prompt_cache import PromptPrefixCacheManager
from src.local_ai_hub.vram_eviction import VramDefragManager


def test_prompt_prefix_cache_lifecycle():
    cache = PromptPrefixCacheManager(max_cached_slots=2)
    sys_a = "You are an assistant."
    rules_a = "Strictly verify evidence before completion."

    # First lookup: miss
    key1, is_hit1 = cache.get_or_register_prefix(sys_a, rules_a, estimated_tokens=50)
    assert is_hit1 is False
    assert key1
    assert cache.cache_hits == 0

    # Second lookup with same prefix: hit!
    key2, is_hit2 = cache.get_or_register_prefix(sys_a, rules_a, estimated_tokens=50)
    assert is_hit2 is True
    assert key2 == key1
    assert cache.cache_hits == 1
    assert cache.hit_ratio() == 0.5


def test_vram_defrag_manager():
    # Mock VRAM: 16 GB total, 3 GB free (headroom 2 GB -> warning if 4 GB requested)
    def mock_vram() -> tuple[float, float]:
        return 16384.0, 3072.0

    defrag = VramDefragManager(min_headroom_mb=2048.0, query_vram_fn=mock_vram)
    vram_status = defrag.inspect_vram()
    assert vram_status.total_mb == 16384.0
    assert vram_status.free_mb == 3072.0

    # Foreground needs 4 GB -> 3072 < 4096 + 2048 (6144) -> should offload
    assert defrag.should_offload_background(required_foreground_mb=4096.0) is True

    # Offload background model
    assert defrag.offload_background_slot("qwen2.5-coder-prep:3b") is True
    assert "qwen2.5-coder-prep:3b" in defrag.stats()["currently_offloaded"]

    # Restore background model
    assert defrag.restore_background_slot("qwen2.5-coder-prep:3b") is True
    assert "qwen2.5-coder-prep:3b" not in defrag.stats()["currently_offloaded"]
