from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from local_ai_hub.accelerators import (
    accelerator_status,
    openvino_cache_dir,
    openvino_device_candidates,
)
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.reranker import Reranker


def test_accelerator_status_malformed_config() -> None:
    # Malformed config sections must not crash accelerator_status
    status = accelerator_status({"models": None, "openvino": None})
    assert isinstance(status, dict)
    assert "embedding" in status
    assert "reranker" in status
    assert status["embedding"]["backend"] == "sentence-transformers"

    # Embedded null byte in cache_dir
    assert openvino_cache_dir({"openvino": {"cache_dir": "bad\0cache"}}) is None
    assert openvino_cache_dir({"openvino": None}) is None


def test_embedding_model_init_malformed_config() -> None:
    # All sub-tables None should not raise AttributeError
    emb = EmbeddingModel({"models": None, "server": None, "features": None, "cpu_retrieval": None, "cache": None})
    assert emb.model_name == "qwen3-embedding:0.6b"
    assert emb.device == "cpu"
    assert emb.max_seq_length >= 128
    assert emb.batch_size >= 1

    # Invalid string / bool in numeric config fields
    emb2 = EmbeddingModel({"cpu_retrieval": {"embedding_max_seq_length": "invalid", "embedding_batch_size": True}})
    assert emb2.max_seq_length == 8192
    assert emb2.batch_size == 32

    # Null bytes stripped from model name
    emb3 = EmbeddingModel({"models": {"embedding": "test\0model\0name"}})
    assert "\0" not in emb3.model_name
    assert emb3.model_name == "testmodelname"


def test_reranker_init_and_candidate_specs_malformed_config() -> None:
    # Candidate specs with None openvino config
    rr = Reranker({"openvino": None, "models": None})
    specs = rr._candidate_specs()
    assert isinstance(specs, list)
    assert len(specs) >= 1
    assert specs[0][0] == "torch"

    # Null bytes stripped
    rr2 = Reranker({"models": {"reranker": "bge\0reranker\0test"}})
    assert "\0" not in rr2.model_name
    assert rr2.model_name == "bgererankertest"
