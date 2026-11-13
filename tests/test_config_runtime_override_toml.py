from __future__ import annotations

import tomllib
import pytest
import local_ai_hub.config as config

from local_ai_hub.config import ConfigError, _dump_toml_tables, save_runtime_overrides


def test_dump_toml_tables_quotes_filename_keys_and_round_trips():
    overrides = {
        "laya": {
            "runtime": {
                "expected_sha256": {
                    "model.safetensors": "a" * 64,
                    "rl_agent_config.json": "b" * 64,
                    "config.json": "c" * 64,
                    "encoder/config.json": "d" * 64,
                    "tokenizer/tokenizer.json": "e" * 64,
                    "tokenizer/tokenizer_config.json": "f" * 64,
                }
            }
        }
    }

    serialized = _dump_toml_tables(overrides)

    assert tomllib.loads(serialized) == overrides


def test_save_runtime_overrides_preserves_quoted_filename_keys(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    runtime_path = tmp_path / "config.runtime.toml"
    original = {
        "laya": {
            "runtime": {
                "expected_sha256": {
                    "model.safetensors": "a" * 64,
                    "rl_agent_config.json": "b" * 64,
                    "config.json": "c" * 64,
                    "encoder/config.json": "d" * 64,
                    "tokenizer/tokenizer.json": "e" * 64,
                    "tokenizer/tokenizer_config.json": "f" * 64,
                }
            }
        }
    }
    runtime_path.write_text(_dump_toml_tables(original), encoding="utf-8")

    save_runtime_overrides(config_path, {"debug_traces": {"enabled": True}})

    updated = tomllib.loads(runtime_path.read_text(encoding="utf-8"))
    assert updated["laya"] == original["laya"]
    assert updated["debug_traces"] == {"enabled": True}


def test_save_runtime_overrides_rejects_invalid_serialization_without_overwriting(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    runtime_path = tmp_path / "config.runtime.toml"
    original = '[debug_traces]\nenabled = false\n'
    runtime_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(config, "_dump_toml_tables", lambda _: '[debug_traces]\nenabled = false\ninvalid key = true\n')

    with pytest.raises(ConfigError, match="serialized runtime overrides are invalid TOML"):
        save_runtime_overrides(config_path, {"debug_traces": {"enabled": True}})

    assert runtime_path.read_text(encoding="utf-8") == original
