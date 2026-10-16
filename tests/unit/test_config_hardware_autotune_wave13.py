from __future__ import annotations

from pathlib import Path
import pytest

from local_ai_hub.config import (
    ConfigError,
    deep_merge,
    get_feature,
    get_table,
    load_config,
    runtime_override_path,
    validate_config,
)
from local_ai_hub.hardware import choose_profile, profile_overrides
from local_ai_hub.autotune import RuntimeTuner


def test_deep_merge_non_dict_base() -> None:
    # Non-dict base should gracefully initialize to empty dict
    res = deep_merge(None, {"key": "value"})  # type: ignore[arg-type]
    assert res == {"key": "value"}

    res2 = deep_merge(123, {"a": 1})  # type: ignore[arg-type]
    assert res2 == {"a": 1}


def test_validate_config_non_dict_and_features() -> None:
    # Non-dict data root must raise ConfigError
    with pytest.raises(ConfigError, match="configuration root must be a TOML table"):
        validate_config(None)  # type: ignore[arg-type]

    # Non-dict features section must raise ConfigError
    with pytest.raises(ConfigError, match=r"\[features\] must be a TOML table"):
        validate_config({"features": "not_a_table"})


def test_config_null_byte_handling() -> None:
    # Embedded null byte in path should raise ConfigError
    with pytest.raises(ConfigError, match="invalid configuration path: embedded null byte"):
        load_config("bad\0path.toml")

    with pytest.raises(ConfigError, match="invalid configuration path: embedded null byte"):
        runtime_override_path("bad\0path.toml")

    # Embedded null byte in allowed_roots
    with pytest.raises(ConfigError, match="security.allowed_roots"):
        validate_config({"security": {"allowed_roots": ["C:\\valid\\root", "bad\0path"]}})


def test_config_get_table_and_get_feature_helpers() -> None:
    # get_table helper returns dict or empty dict
    assert get_table({"models": {"fast": "3b"}}, "models") == {"fast": "3b"}
    assert get_table({"models": None}, "models") == {}
    assert get_table({"models": "string"}, "models") == {}
    assert get_table(None, "models") == {}

    # get_feature helper returns boolean or default
    assert get_feature({"features": {"rag": False}}, "rag") is False
    assert get_feature({"features": {"rag": True}}, "rag") is True
    assert get_feature({"features": None}, "rag", default=True) is True
    assert get_feature({"features": {"rag": "not_bool"}}, "rag", default=True) is True
    assert get_feature(None, "rag", default=False) is False


def test_hardware_profile_overrides_null_handling() -> None:
    # profile_overrides with None ram or gpus should not crash with AttributeError
    res = profile_overrides("integrated", {"ram": None, "gpus": None})
    assert isinstance(res, dict)

    # choose_profile with malformed elements and negative ram
    profile = choose_profile([None, "not_a_dict", {"vram_mb": "invalid"}], -5.0)  # type: ignore[list-item]
    assert profile in {"cpu", "low", "balanced", "high", "max", "integrated"}


def test_autotune_bool_guard_and_null_bytes(tmp_path: Path) -> None:
    # Malformed state_dir with null byte
    tuner = RuntimeTuner({"server": {"state_dir": "bad\0dir"}})
    assert tuner.enabled is True

    # Observe with boolean in numeric fields
    tuner.observe("test-model", {"eval_count": True, "load_duration_ns": False}, 100.0)
    profile = tuner.get_model_profile("test-model")
    assert profile is not None
    # TPS should be 0.0 because eval_count was boolean (ignored/0.0)
    assert profile["tps"] == 0.0
