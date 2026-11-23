"""Tests for Blackwell hardware pipeline detection and execution profile."""

from src.local_ai_hub.blackwell_pipeline import detect_blackwell_profile


def test_detect_blackwell_profile():
    profile = detect_blackwell_profile()
    assert profile.device_name
    assert isinstance(profile.compute_capability, tuple)
    if profile.compute_capability[0] >= 10 or "5070" in profile.device_name:
        assert profile.has_tma is True
        assert profile.fp8_gemm_supported is True
        assert profile.kv_cache_format == "fp8_e4m3"
        assert profile.max_context_tokens >= 32768
