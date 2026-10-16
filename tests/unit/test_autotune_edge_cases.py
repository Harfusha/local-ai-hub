from __future__ import annotations

import math
from pathlib import Path

import pytest

from local_ai_hub.autotune import RuntimeTuner


def test_runtime_tuner_safe_config_initialization(tmp_path: Path) -> None:
    # None config or non-dict config
    tuner_none = RuntimeTuner(None)  # type: ignore[arg-type]
    assert tuner_none.enabled is True
    assert tuner_none.min_samples >= 1
    assert 0.01 <= tuner_none.alpha <= 1.0

    tuner_default_config = RuntimeTuner({"autotune": {"ema_alpha": 0.20, "persist": False}})
    assert tuner_default_config.alpha == 0.20
    with pytest.raises(ValueError, match="ema_alpha"):
        RuntimeTuner({"autotune": {"ema_alpha": "invalid", "persist": False}})


def test_runtime_tuner_observe_edge_cases_poison_prevention(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "autotune": {"enabled": True, "min_samples": 2, "persist": False},
    }
    tuner = RuntimeTuner(config)

    # Empty model name, non-dict result, or non-finite elapsed_ms are safely ignored
    tuner.observe("", {"eval_count": 10}, 100.0)
    assert tuner.has_model("") is False

    tuner.observe("model-1", "not-a-dict", 100.0)  # type: ignore[arg-type]
    assert tuner.has_model("model-1") is False

    tuner.observe("model-1", {"eval_count": 10}, float("nan"))
    assert tuner.has_model("model-1") is False

    tuner.observe("model-1", {"eval_count": 10}, -50.0)
    assert tuner.has_model("model-1") is False

    # Corrupt metric fields are ignored so they cannot poison the profile.
    tuner.observe(
        "model-1",
        {
            "load_duration_ns": "invalid",
            "eval_count": float("nan"),
            "eval_duration_ns": -100,
        },
        120.0,
    )
    assert tuner.has_model("model-1") is False
    assert tuner.get_model_profile("model-1") is None


def test_runtime_tuner_inspection_and_reset(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "autotune": {"enabled": True, "min_samples": 2, "persist": False},
    }
    tuner = RuntimeTuner(config)

    tuner.observe("m1", {"eval_count": 20, "eval_duration_ns": 1_000_000_000}, 50.0)
    tuner.observe("m2", {"eval_count": 30, "eval_duration_ns": 1_000_000_000}, 80.0)

    assert tuner.has_model("m1") is True
    assert tuner.has_model("m2") is True
    assert tuner.has_model("m3") is False
    assert set(tuner.model_names()) == {"m1", "m2"}

    # Reset specific model
    tuner.reset("m1")
    assert tuner.has_model("m1") is False
    assert tuner.has_model("m2") is True

    # Reset all models
    tuner.reset()
    assert tuner.has_model("m2") is False
    assert tuner.model_names() == []
