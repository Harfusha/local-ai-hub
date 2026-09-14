from __future__ import annotations

from pathlib import Path

import pytest
from local_ai_hub.config import ConfigError, load_config
from local_ai_hub.hardware import choose_profile


def _config(tmp_path: Path, extra: str = "", server_bind: str | None = None):
    path = tmp_path / "config.toml"
    bind_line = f'bind = "{server_bind}"\n' if server_bind else ""
    path.write_text(
        f'''[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n{bind_line}[hardware]\nprofile = "cpu"\nauto_tune = true\n{extra}\n''',
        encoding="utf-8",
    )
    return load_config(str(path))


def test_cpu_profile_selects_small_models(tmp_path: Path):
    cfg = _config(tmp_path)
    assert cfg["_hardware"]["profile"] == "cpu"
    assert cfg["models"]["background_code"] == "qwen2.5-coder:1.5b-instruct-q5_K_M"
    assert cfg["models"]["fast_code"] == "qwen2.5-coder:3b-instruct-q5_K_M"
    assert cfg["models"]["heavy_code"] == "qwen2.5-coder:7b-instruct-q5_K_M"
    assert cfg["background_gpu"]["enabled"] is False


def test_background_work_defaults_to_low_os_priority(tmp_path: Path):
    cfg = _config(tmp_path)
    assert cfg["preprocessing"]["cpu_priority"] == "idle"
    assert cfg["background_gpu"]["process_priority"] == "idle"


def test_explicit_model_override_wins(tmp_path: Path):
    cfg = _config(tmp_path, '[models]\nfast_code = "custom:latest"')
    assert cfg["models"]["fast_code"] == "custom:latest"


def test_profile_selection_thresholds():
    assert choose_profile([], 8, "auto") == "cpu"
    assert choose_profile([], 32, "auto") == "low"
    assert choose_profile([{"vendor": "nvidia", "vram_mb": 8 * 1024}], 32, "auto") == "balanced"
    assert choose_profile([{"vendor": "nvidia", "vram_mb": 16 * 1024}], 32, "auto") == "high"
    assert choose_profile([{"vendor": "nvidia", "vram_mb": 24 * 1024}], 64, "auto") == "max"
    assert choose_profile([{"vendor": "apple", "unified_memory_mb": 32 * 1024}], 32, "auto") == "high"


def test_security_validation_refuses_unconfigured_remote_bind(tmp_path: Path):
    with pytest.raises(ConfigError, match="Refusing non-loopback"):
        _config(tmp_path, server_bind="0.0.0.0")


def test_security_validation_requires_token_for_remote(tmp_path: Path):
    with pytest.raises(ConfigError, match="api_token with at least 16 characters"):
        _config(tmp_path, '[security]\nallow_remote = true\napi_token = "short"\n', server_bind="0.0.0.0")


def test_security_validation_accepts_valid_remote_token(tmp_path: Path):
    cfg = _config(
        tmp_path,
        '[security]\nallow_remote = true\napi_token = "very-long-secure-secret-token-1234"\n',
        server_bind="0.0.0.0",
    )
    assert cfg["server"]["bind"] == "0.0.0.0"
    assert cfg["security"]["allow_remote"] is True
