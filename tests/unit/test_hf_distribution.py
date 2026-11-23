"""Unit tests for automated Hugging Face publishing and download pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.download_hf_model import download_model, update_config_file
from tools.model_training.publish_hf import (
    FORBIDDEN_UPLOAD_PATTERNS,
    generate_model_card,
    publish_matrix_to_hf,
    publish_run_to_hf,
    resolve_hf_token,
)


def test_resolve_hf_token_explicit() -> None:
    assert resolve_hf_token("hf_test123") == "hf_test123"


def test_resolve_hf_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_env_token_456")
    assert resolve_hf_token() == "hf_env_token_456"


def test_resolve_hf_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    with patch("huggingface_hub.get_token", return_value=None):
        with pytest.raises(RuntimeError, match="Hugging Face token not found"):
            resolve_hf_token()


def test_generate_model_card_for_lora(tmp_path: Path) -> None:
    run_dir = tmp_path / "qwen-run"
    run_dir.mkdir()
    adapter_dir = run_dir / "adapter"
    adapter_dir.mkdir()

    training_run = {
        "base_model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "task_type": "preprocess_card",
        "epochs": 3,
        "quantization": "4bit",
        "gpu": "NVIDIA GeForce RTX 5070 Ti",
        "elapsed_seconds": 120.5,
    }
    (adapter_dir / "training_run.json").write_text(json.dumps(training_run), encoding="utf-8")

    before = {"summary": {"base": {"schema_pass_rate": 0.5, "fact_recall": 0.2}}}
    after = {"summary": {"schema_pass_rate": 1.0, "fact_recall": 0.6}}
    (run_dir / "benchmark-before.json").write_text(json.dumps(before), encoding="utf-8")
    (run_dir / "benchmark-after.json").write_text(json.dumps(after), encoding="utf-8")

    card = generate_model_card(run_dir, "testuser/test-qwen-lora", is_laya=False)

    assert "license: apache-2.0" in card
    assert "base_model: Qwen/Qwen2.5-Coder-1.5B-Instruct" in card
    assert "pipeline_tag: text-generation" in card
    assert "schema_pass_rate" in card
    assert "| `schema_pass_rate` | 0.5000 | 1.0000 | +0.5000 |" in card
    assert "python tools/download_hf_model.py --repo testuser/test-qwen-lora" in card


def test_generate_model_card_for_laya(tmp_path: Path) -> None:
    run_dir = tmp_path / "laya-run"
    run_dir.mkdir()
    ckpt_dir = run_dir / "checkpoint"
    ckpt_dir.mkdir()

    training_run = {
        "base_model": "convaiinnovations/laya-multilingual",
        "task_type": "decision_model",
        "epochs": 4,
    }
    (run_dir / "training-run.json").write_text(json.dumps(training_run), encoding="utf-8")

    card = generate_model_card(run_dir, "testuser/laya-decision", is_laya=True)

    assert "license: apache-2.0" in card
    assert "base_model: convaiinnovations/laya-multilingual" in card
    assert "pipeline_tag: text-classification" in card
    assert "checkpoint_path = \"testuser/laya-decision\"" in card


def test_publish_run_to_hf_validates_and_uploads(tmp_path: Path) -> None:
    run_dir = tmp_path / "test-model"
    run_dir.mkdir()
    adapter_dir = run_dir / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "adapter_model.safetensors").write_text("fake weights", encoding="utf-8")
    (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")

    mock_api = MagicMock()
    with patch("huggingface_hub.HfApi", return_value=mock_api):
        res = publish_run_to_hf(run_dir, "myuser/my-model", token="hf_mock_token")

    assert res["success"] is True
    assert res["repo_id"] == "myuser/my-model"
    mock_api.create_repo.assert_called_once_with(repo_id="myuser/my-model", private=False, exist_ok=True, repo_type="model")
    mock_api.upload_folder.assert_called_once()
    _, kwargs = mock_api.upload_folder.call_args
    assert kwargs["ignore_patterns"] == FORBIDDEN_UPLOAD_PATTERNS
    assert kwargs["repo_id"] == "myuser/my-model"


def test_publish_matrix_to_hf(tmp_path: Path) -> None:
    matrix_dir = tmp_path / "matrix"
    matrix_dir.mkdir()
    m1 = matrix_dir / "qwen-0.5b"
    m1.mkdir()
    (m1 / "adapter").mkdir()
    (m1 / "adapter" / "adapter_model.safetensors").write_text("fake 0.5b", encoding="utf-8")

    m2 = matrix_dir / "qwen-1.5b"
    m2.mkdir()
    (m2 / "adapter").mkdir()
    (m2 / "adapter" / "adapter_model.safetensors").write_text("fake 1.5b", encoding="utf-8")

    mock_api = MagicMock()
    with patch("huggingface_hub.HfApi", return_value=mock_api):
        results = publish_matrix_to_hf(matrix_dir, "myuser", token="hf_mock_token")

    assert len(results) == 2
    repo_ids = {r["repo_id"] for r in results}
    assert "myuser/qwen-0.5b" in repo_ids
    assert "myuser/qwen-1.5b" in repo_ids


def test_download_model_and_update_config(tmp_path: Path) -> None:
    mock_api = MagicMock()
    mock_info = MagicMock()
    mock_info.sha = "1234567890abcdef"
    mock_api.repo_info.return_value = mock_info

    def fake_snapshot_download(repo_id, local_dir, **kwargs):
        dest = Path(local_dir)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "adapter_config.json").write_text("{}", encoding="utf-8")
        (dest / "adapter_model.safetensors").write_text("weights", encoding="utf-8")
        return str(dest)

    with patch("huggingface_hub.HfApi", return_value=mock_api):
        with patch("huggingface_hub.snapshot_download", side_effect=fake_snapshot_download):
            dest_dir = tmp_path / "models" / "downloaded-model"
            res = download_model("myuser/my-lora", destination=dest_dir, token="hf_mock")

    assert res["success"] is True
    assert res["model_type"] == "lora"
    assert res["commit_sha"] == "1234567890abcdef"

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[server]\nport = 11435\n", encoding="utf-8")
    update_config_file(cfg_file, res)

    new_cfg = cfg_file.read_text(encoding="utf-8")
    assert "[models]" in new_cfg
    assert "preprocessing_adapter =" in new_cfg
    assert "downloaded-model" in new_cfg
