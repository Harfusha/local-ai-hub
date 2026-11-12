from __future__ import annotations

import tomllib

from local_ai_hub.config import _dump_toml_tables, save_runtime_overrides


def test_dump_toml_tables_quotes_filename_keys_and_round_trips():
    overrides = {
        "laya": {
            "runtime": {
                "expected_sha256": {
                    "model.safetensors": "a" * 64,
                    "encoder/config.json": "b" * 64,
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
                    "encoder/config.json": "b" * 64,
                }
            }
        }
    }
    runtime_path.write_text(_dump_toml_tables(original), encoding="utf-8")

    save_runtime_overrides(config_path, {"debug_traces": {"enabled": True}})

    updated = tomllib.loads(runtime_path.read_text(encoding="utf-8"))
    assert updated["laya"] == original["laya"]
    assert updated["debug_traces"] == {"enabled": True}
