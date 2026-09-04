from __future__ import annotations

from pathlib import Path

from local_ai_hub.config import load_config
from local_ai_hub.hardware import choose_profile


def _config(tmp_path: Path, extra: str = ""):
    path = tmp_path / "config.toml"
    path.write_text(
        f'''[server]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n[hardware]\nprofile = "cpu"\nauto_tune = true\n{extra}\n''',
        encoding="utf-8",
    )
    return load_config(str(path))


def test_cpu_profile_selects_small_models(tmp_path: Path):
    cfg = _config(tmp_path)
    assert cfg["_hardware"]["profile"] == "cpu"
    assert cfg["models"]["background_code"] == "qwen2.5-coder:0.5b"
    assert cfg["models"]["fast_code"] == "qwen2.5-coder:1.5b"
    assert cfg["models"]["heavy_code"] == "qwen2.5-coder:3b"
    assert cfg["background_gpu"]["enabled"] is False


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
