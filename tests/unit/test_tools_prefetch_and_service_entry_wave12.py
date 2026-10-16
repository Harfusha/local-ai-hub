from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.service_entry import resolve_service_config
from tools.prefetch_local_nlp import run_prefetch_local_nlp
from tools.prefetch_openvino import run_prefetch_openvino
from tools.resolve_hub_pids import _owned_hub_pid


def test_service_entry_resolve_config_null_bytes(tmp_path: Path) -> None:
    # Embedded null byte in arguments should be rejected safely
    bad_argv = ["service_entry.py", "--config", "bad\0path.toml"]
    assert resolve_service_config(bad_argv, root=tmp_path, env={}) is None


def test_service_entry_resolve_config_valid_and_fallback(tmp_path: Path) -> None:
    cfg = tmp_path / "custom.toml"
    cfg.write_text("[server]\nport = 8000\n", encoding="utf-8")
    argv = ["service_entry.py", "--config", str(cfg)]
    resolved = resolve_service_config(argv, root=tmp_path, env={})
    assert resolved == cfg.resolve()

    # Fallback when no argv given and root/config.toml exists
    root_cfg = tmp_path / "config.toml"
    root_cfg.write_text("[server]\nport = 9000\n", encoding="utf-8")
    fallback = resolve_service_config([], root=tmp_path, env={})
    assert fallback == root_cfg.resolve()

    # Env fallback when no argv and no root config
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    env_cfg = tmp_path / "env_config.toml"
    env_cfg.write_text("[server]\nport = 9001\n", encoding="utf-8")
    env_fallback = resolve_service_config([], root=other_dir, env={"LOCAL_AI_CONFIG": str(env_cfg)})
    assert env_fallback == env_cfg.resolve()


def test_prefetch_local_nlp_malformed_config() -> None:
    # Disabled features with invalid models
    disabled_report = run_prefetch_local_nlp({"features": {"rag": False, "reranker": False}, "models": "invalid"})
    assert disabled_report["success"] is True
    assert disabled_report["embedding"] is None
    assert disabled_report["reranker"] is None

    # Malformed features or models with mocked models
    with patch("tools.prefetch_local_nlp.EmbeddingModel") as mock_emb, patch("tools.prefetch_local_nlp.Reranker") as mock_rr:
        mock_emb_inst = MagicMock()
        mock_emb_inst.encode.return_value = {"success": True}
        mock_emb_inst.model_name = "test-model"
        mock_emb_inst.device = "cpu"
        mock_emb.return_value = mock_emb_inst

        mock_rr_inst = MagicMock()
        mock_rr_inst._ensure_model.return_value = True
        mock_rr_inst.model_name = "test-rr"
        mock_rr_inst.device = "cpu"
        mock_rr.return_value = mock_rr_inst

        report = run_prefetch_local_nlp({"features": None, "models": None})
        assert report["success"] is True
        assert report["embedding"]["model"] == "test-model"
        assert report["reranker"]["model"] == "test-rr"


def test_prefetch_openvino_malformed_config() -> None:
    # Malformed features or models should not raise AttributeError
    malformed_cfg = {"features": "invalid", "models": 123}
    report = run_prefetch_openvino(malformed_cfg)
    assert isinstance(report, dict)
    assert "accelerators" in report


def test_resolve_hub_pids_hardening(tmp_path: Path) -> None:
    # Null byte or non-string path rejected cleanly
    assert _owned_hub_pid("bad\0config.toml") is None
    assert _owned_hub_pid(None) is None  # type: ignore[arg-type]

    # Non-existent config file
    assert _owned_hub_pid(str(tmp_path / "nonexistent.toml")) is None

    # Config pointing to non-existent state_dir
    cfg_file = tmp_path / "custom_state_cfg.toml"
    cfg_file.write_text(f'[server]\nstate_dir = "{(tmp_path / "no_such_state").as_posix()}"\n', encoding="utf-8")
    assert _owned_hub_pid(str(cfg_file)) is None

    # Corrupt owner file (invalid json)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    valid_cfg = tmp_path / "valid_cfg.toml"
    valid_cfg.write_text(f'[server]\nstate_dir = "{state_dir.as_posix()}"\n', encoding="utf-8")
    owner_file = state_dir / "hub.owner.json"
    owner_file.write_text("NOT_JSON{", encoding="utf-8")
    pid_file = state_dir / "hub.pid"
    pid_file.write_text("1234\n", encoding="utf-8")
    assert _owned_hub_pid(str(valid_cfg)) is None
