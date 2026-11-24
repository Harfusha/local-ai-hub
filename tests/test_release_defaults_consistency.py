from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_defaults_match_repository_defaults_and_enable_concise_local_output():
    repository_defaults = tomllib.loads((ROOT / "defaults.toml").read_text(encoding="utf-8"))
    packaged_defaults = tomllib.loads(
        (ROOT / "src" / "local_ai_hub" / "defaults.toml").read_text(encoding="utf-8")
    )

    assert packaged_defaults == repository_defaults
    assert repository_defaults["token_saving"]["concise_local_output"] is True
    assert repository_defaults["background_gpu"]["enabled"] is False
    assert repository_defaults["background_gpu"]["cpu_fallback_enabled"] is True
    assert repository_defaults["models"]["allow_hf_downloads"] is True
    assert repository_defaults["laya"]["enabled"] is True
    assert "mode" not in repository_defaults["laya"]
    assert repository_defaults["agents"]["antigravity"] is True
    assert repository_defaults["agents"]["opencode_plugin_route"] is True
    retired_models = {"qwen3.5:4b-q4_K_M", "gemma4:12b", "qwen2.5-coder:14b"}
    assert retired_models.isdisjoint(repository_defaults["models"].values())


def test_example_config_shows_active_laya_and_default_checkpoint_downloads():
    example = tomllib.loads((ROOT / "config.toml.example").read_text(encoding="utf-8"))

    assert example["laya"]["enabled"] is True
    assert "mode" not in example["laya"]
    assert example["laya"]["idle_unload_seconds"] == 600
    assert example["models"]["allow_hf_downloads"] is True
