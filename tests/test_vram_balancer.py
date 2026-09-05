from __future__ import annotations

from unittest.mock import patch
import pytest
from local_ai_hub.vram_balancer import VRAMBalancer


def test_vram_balancer_nominal_pressure():
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b", "draft_code": "qwen2.5-coder:1.5b"}})
    mock_gpu = {
        "available": True,
        "vendor": "nvidia",
        "gpu_name": "NVIDIA GeForce RTX 4090",
        "vram_total_mb": 24576.0,
        "vram_used_mb": 6144.0,
        "vram_used_pct": 25.0,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=mock_gpu):
        st = balancer.status()
        assert st["pressure_level"] == "nominal"
        assert st["context_budget_factor"] == 1.0
        assert st["throttle_background"] is False
        assert st["dynamic_context_tokens"] >= 32768
        assert st["speculative_inference"]["draft_model"] == "qwen2.5-coder:1.5b"
        assert st["speculative_inference"]["strategy"] == "full_capacity"


def test_vram_balancer_high_pressure_downscale():
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b"}})
    mock_gpu = {
        "available": True,
        "vendor": "nvidia",
        "gpu_name": "NVIDIA GeForce RTX 3080",
        "vram_total_mb": 10240.0,
        "vram_used_mb": 9000.0,
        "vram_used_pct": 87.8,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=mock_gpu):
        st = balancer.status()
        assert st["pressure_level"] == "high"
        assert st["context_budget_factor"] == 0.5
        assert st["throttle_background"] is True
        assert balancer.should_throttle_background() is True
        assert balancer.recommended_context_budget(32768) == 16384


def test_vram_balancer_critical_pressure():
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:7b"}})
    mock_gpu = {
        "available": True,
        "vendor": "nvidia",
        "gpu_name": "NVIDIA GeForce RTX 3060",
        "vram_total_mb": 12288.0,
        "vram_used_mb": 11800.0,
        "vram_used_pct": 96.0,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=mock_gpu):
        st = balancer.status()
        assert st["pressure_level"] == "critical"
        assert st["context_budget_factor"] == 0.25
        assert st["throttle_background"] is True
        assert balancer.recommended_context_budget(32768) == 8192
        assert "throttled" in st["speculative_inference"]["strategy"]
