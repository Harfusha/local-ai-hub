from __future__ import annotations

import pytest

from local_ai_hub.operational_mode import set_operational_mode
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize("mode", ["gaming", "maintenance"])
def test_restored_inference_gate_precedes_runtime_initialization(tmp_path, mode):
    set_operational_mode(tmp_path, mode)
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    result = service._generate("model", "prompt", "system", 64, 0.0, "tenant", "mcp", 0)
    assert result["success"] is False
    assert result["mode"] == mode
    assert result["error_code"] == "operational_mode_blocked"


@pytest.mark.parametrize("action", ["start", "refresh", "resume"])
def test_restored_preprocess_gate_precedes_mutating_backend(tmp_path, action):
    set_operational_mode(tmp_path, "maintenance")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    result = service.preprocess({"action": action})
    assert result["success"] is False
    assert result["mode"] == "maintenance"


def test_restored_background_gate_precedes_gpu_access(tmp_path):
    set_operational_mode(tmp_path, "gaming")
    processor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    processor.state_dir = tmp_path
    processor._gpu_yield = lambda: pytest.fail("GPU accessed while paused")
    result = processor._run_background_generate("model", "prompt", "system", {}, 64, "preprocess:test")
    assert result["success"] is False
    assert result["mode"] == "gaming"
