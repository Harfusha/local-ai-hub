from __future__ import annotations

from unittest.mock import patch
import pytest

from local_ai_hub.model_policy import ModelExecutionPolicy
from local_ai_hub.ollama import RepetitionWatchdog
from local_ai_hub.vram_balancer import VRAMBalancer
from local_ai_hub.hardware import profile_overrides


def test_apply_payload_injects_repetition_penalty_for_small_models():
    cfg = {
        "models": {
            "fast_code": "qwen2.5-coder:1.5b",
            "heavy_code": "qwen2.5-coder:3b",
        },
        "model_execution": {},
    }
    policy = ModelExecutionPolicy(cfg)

    # Small 3B model with near-zero temperature should get repeat_penalty and clamped temperature
    clean, profile = policy.apply_payload(
        "qwen2.5-coder:3b",
        {"model": "qwen2.5-coder:3b", "prompt": "test", "options": {"temperature": 0.05}},
    )
    opts = clean["options"]
    assert opts["repeat_penalty"] == 1.18
    assert opts["repeat_last_n"] == 128
    assert opts["temperature"] == 0.20

    # Caller explicitly specifying custom repeat_penalty is respected
    clean2, _ = policy.apply_payload(
        "qwen2.5-coder:3b",
        {"model": "qwen2.5-coder:3b", "prompt": "test", "options": {"repeat_penalty": 1.25, "temperature": 0.5}},
    )
    assert clean2["options"]["repeat_penalty"] == 1.25
    assert clean2["options"]["temperature"] == 0.5

    # 7B model should not have temperature clamped
    clean7, _ = policy.apply_payload(
        "qwen2.5-coder:7b",
        {"model": "qwen2.5-coder:7b", "prompt": "test", "options": {"temperature": 0.05}},
    )
    assert clean7["options"]["temperature"] == 0.05
    assert clean7["options"]["repeat_penalty"] == 1.12


def test_repetition_watchdog_detects_2_line_cycle():
    watchdog = RepetitionWatchdog(max_repeat=3)

    chunks = [
        "- **LOCAL AI HUB TOOL POLICY**:\n",
        "  - **Policy**:\n",
        "    - **User Request**:\n",
        "  - **Policy**:\n",
        "    - **User Request**:\n",
        "  - **Policy**:\n",
        "    - **User Request**:\n",
    ]

    detected = False
    for chunk in chunks:
        if watchdog.push(chunk):
            detected = True
            break

    assert detected is True
    assert watchdog.loop_detected is True


def test_repetition_watchdog_detects_1_line_cycle():
    watchdog = RepetitionWatchdog(max_repeat=3)

    chunks = [
        "First line\n",
        "Same repeated line\n",
        "Same repeated line\n",
        "Same repeated line\n",
    ]

    detected = False
    for chunk in chunks:
        if watchdog.push(chunk):
            detected = True
            break

    assert detected is True
    assert watchdog.loop_detected is True


def test_repetition_watchdog_ignores_normal_code():
    watchdog = RepetitionWatchdog(max_repeat=3)

    chunks = [
        "def example():\n",
        "    x = 1\n",
        "    y = 2\n",
        "    z = x + y\n",
        "    return z\n",
    ]

    detected = False
    for chunk in chunks:
        if watchdog.push(chunk):
            detected = True
            break

    assert detected is False
    assert watchdog.loop_detected is False


def test_vram_balancer_nominal_for_integrated_gpu():
    balancer = VRAMBalancer({"models": {"fast_code": "qwen2.5-coder:3b"}})
    mock_gpu = {
        "available": True,
        "vendor": "intel",
        "gpu_name": "Intel(R) Iris(R) Xe Graphics",
        "vram_total_mb": 0.0,
        "reported_adapter_memory_mb": 1024.0,
        "integrated": True,
        "shared_memory": True,
        "vram_used_mb": 0.0,
        "vram_used_pct": 0.0,
    }
    with patch("local_ai_hub.vram_balancer.get_gpu_telemetry", return_value=mock_gpu):
        st = balancer.status()
        assert st["pressure_level"] == "nominal"
        assert st["context_budget_factor"] == 1.0
        assert st["throttle_background"] is False


def test_hardware_integrated_profile_ram_scaling():
    # When 32GB RAM is detected, integrated profile scales context to 32768
    detected_32gb = {
        "ram": {"total_gb": 32.0, "available_gb": 24.0},
        "gpus": [{"vendor": "intel", "integrated": True}],
    }
    overrides_32 = profile_overrides("integrated", detected_32gb)
    exec_cfg_32 = overrides_32["model_execution"]
    assert exec_cfg_32["fast"]["context_tokens"] == 32768
    assert exec_cfg_32["smart"]["context_tokens"] == 32768
    assert exec_cfg_32["smart"]["max_prompt_tokens"] == 24000

    # When 16GB RAM is detected, scales to 16384
    detected_16gb = {
        "ram": {"total_gb": 16.0, "available_gb": 10.0},
        "gpus": [{"vendor": "intel", "integrated": True}],
    }
    overrides_16 = profile_overrides("integrated", detected_16gb)
    exec_cfg_16 = overrides_16["model_execution"]
    assert exec_cfg_16["fast"]["context_tokens"] == 16384
    assert exec_cfg_16["smart"]["context_tokens"] == 16384

    # When 8GB RAM is detected, stays at default 8192
    detected_8gb = {
        "ram": {"total_gb": 8.0, "available_gb": 4.0},
        "gpus": [{"vendor": "intel", "integrated": True}],
    }
    overrides_8 = profile_overrides("integrated", detected_8gb)
    assert overrides_8["model_execution"]["fast"]["context_tokens"] == 8192


def test_hardware_integrated_profile_enables_openvino_with_npu():
    detected = {
        "ram": {"total_gb": 32.0, "available_gb": 24.0},
        "gpus": [{"vendor": "intel", "integrated": True}],
        "npus": [{"vendor": "intel", "name": "Intel AI Boost NPU"}],
    }
    overrides = profile_overrides("integrated", detected)
    assert overrides["models"]["embedding_backend"] == "openvino"
    assert overrides["models"]["reranker_backend"] == "openvino"
    assert overrides["openvino"]["enabled"] is True


def test_profile_overrides_cpu_and_integrated_defaults():
    from local_ai_hub.hardware import PROFILE_OVERRIDES
    cpu = PROFILE_OVERRIDES["cpu"]
    integ = PROFILE_OVERRIDES["integrated"]

    assert cpu["ollama"]["kv_cache_type"] == "q4_0"
    assert cpu["ollama"]["keep_alive"] == "5m"
    assert cpu["preprocessing"]["cpu_workers"] == 1
    assert cpu["local_pipeline"]["same_model_worker_passes"] == 1

    assert integ["ollama"]["kv_cache_type"] == "q4_0"
    assert integ["ollama"]["keep_alive"] == "5m"
    assert integ["preprocessing"]["cpu_workers"] == 1
    assert integ["local_pipeline"]["same_model_worker_passes"] == 1


def test_ollama_runtime_environment_threads_and_keepalive(tmp_path):
    from local_ai_hub.ollama import OllamaRuntime
    cfg = {
        "server": {"ollama_url": "http://127.0.0.1:11434", "state_dir": str(tmp_path)},
        "ollama": {"num_threads": 4, "keep_alive": "5m", "kv_cache_type": "q4_0"},
    }
    runtime = OllamaRuntime(cfg)
    env = runtime._configured_environment()
    assert env["OLLAMA_NUM_THREADS"] == "4"
    assert env["OLLAMA_KEEP_ALIVE"] == "5m"
    assert env["OLLAMA_KV_CACHE_TYPE"] == "q4_0"

