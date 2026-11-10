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


def test_openvino_npu_reranker_uses_static_shape_before_compile() -> None:
    rr = Reranker({
        "models": {"reranker": "test-reranker", "reranker_backend": "openvino", "reranker_device": "NPU"},
        "cpu_retrieval": {"reranker_batch_size": 8, "reranker_max_length": 384},
    })
    rr._candidate_specs = lambda: [("openvino", "NPU")]
    ov_model = MagicMock()
    cross_encoder = MagicMock(transformers_model=ov_model)
    cross_encoder_factory = MagicMock(return_value=cross_encoder)
    sentence_transformers = MagicMock(CrossEncoder=cross_encoder_factory)

    with patch.dict("sys.modules", {"sentence_transformers": sentence_transformers}):
        with patch(
            "local_ai_hub.reranker.load_model",
            side_effect=lambda _owner, *, uses_cuda, factory: factory(),
        ):
            assert rr._load_candidate(0)

    model_kwargs = cross_encoder_factory.call_args.kwargs["model_kwargs"]
    assert model_kwargs == {"device": "npu", "compile": False}
    ov_model.reshape.assert_called_once_with(8, 384)
    ov_model.compile.assert_called_once_with()


def test_openvino_npu_reranker_predict_pads_partial_static_batch() -> None:
    rr = Reranker({
        "models": {"reranker_backend": "openvino", "reranker_device": "NPU"},
        "cpu_retrieval": {"reranker_max_length": 384, "reranker_batch_size": 8},
    })
    rr.active_backend = "openvino"
    rr.active_device = "NPU"
    rr._model = MagicMock()
    rr._ensure_model = MagicMock(return_value=True)
    rr._model.predict.return_value = list(range(8))
    pairs = [("query", "document one"), ("query", "document two")]

    assert rr._predict(pairs, priority=1) == [0, 1]

    rr._model.predict.assert_called_once_with(
        pairs + [pairs[-1]] * 6,
        batch_size=8,
        show_progress_bar=False,
        processing_kwargs={
            "text": {"padding": "max_length", "max_length": 384, "truncation": True}
        },
    )


def test_openvino_npu_reranker_without_transformer_uses_cpu_fallback() -> None:
    rr = Reranker({
        "models": {"reranker": "test-reranker", "reranker_backend": "openvino", "reranker_device": "NPU"},
    })
    rr._candidate_specs = lambda: [("openvino", "NPU"), ("torch", "cpu")]
    cross_encoder_factory = MagicMock(side_effect=[object(), object()])
    sentence_transformers = MagicMock(CrossEncoder=cross_encoder_factory)

    with patch.dict("sys.modules", {"sentence_transformers": sentence_transformers}):
        with patch(
            "local_ai_hub.reranker.load_model",
            side_effect=lambda _owner, *, uses_cuda, factory: factory(),
        ):
            assert rr._ensure_model()

    assert rr.active_backend == "torch"
    assert rr.active_device == "cpu"
    assert cross_encoder_factory.call_count == 2


def test_embedding_encode_discovers_accelerator_candidates_once_per_request() -> None:
    embedding = EmbeddingModel({
        "models": {"embedding_backend": "auto", "embedding_device": "auto"},
        "cache": {"embeddings": False},
    })
    candidates = [("sentence-transformers", "cuda:0"), ("sentence-transformers", "cpu")]
    embedding._candidate_specs = MagicMock(return_value=candidates)
    embedding._claim_embedding_gpu = MagicMock(return_value=None)
    embedding._encode_uncached = MagicMock(return_value={
        "success": True, "embeddings": [[1.0]], "computed": 1,
    })
    embedding.flight_group.do = lambda _key, work: (work(), False)

    def uses_cuda(_backend, device):
        return str(device).lower().startswith("cuda")

    with patch("local_ai_hub.embeddings.uses_torch_cuda", side_effect=uses_cuda):
        result = embedding.encode(["candidate probe test"])

    assert result["success"] is True
    assert embedding._candidate_specs.call_count == 1
