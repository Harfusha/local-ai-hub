from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import local_ai_hub.accelerators as accelerators
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
    assert status["embedding"]["backend"] == "auto"
    assert status["embedding"]["candidates"] == [("sentence-transformers", "cpu")]

    # Embedded null byte in cache_dir
    assert openvino_cache_dir({"openvino": {"cache_dir": "bad\0cache"}}) is None
    assert openvino_cache_dir({"openvino": None}) is None


def test_intel_only_accelerator_status_does_not_import_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accelerators, "openvino_runtime", lambda: {"available": True, "devices": ["NPU"]})
    monkeypatch.setattr(accelerators, "openvino_device_candidates", lambda *_args: ["NPU"])
    monkeypatch.setattr(accelerators, "_onnx_providers", lambda: set())
    monkeypatch.setattr("local_ai_hub.hardware.detect_hardware", lambda *_args, **_kwargs: {
        "gpus": [{"vendor": "intel", "integrated": True}], "npus": []
    })
    monkeypatch.setattr(accelerators, "_torch_gpu_route", lambda: pytest.fail("Torch probe should be skipped"))

    status = accelerator_status({"models": {"embedding_backend": "auto", "embedding_device": "auto"}})

    assert status["embedding"]["torch_gpu_available"] is False
    assert status["embedding"]["candidates"] == [
        ("openvino", "NPU"), ("sentence-transformers", "cpu"),
    ]


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


def test_explicit_cuda_embedding_does_not_add_cpu_fallback() -> None:
    embedding = EmbeddingModel({
        "models": {"embedding_backend": "sentence-transformers", "embedding_device": "cuda"},
    })

    assert embedding._candidate_specs() == [("sentence-transformers", "cuda")]


def test_automatic_embedding_route_keeps_cpu_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    embedding = EmbeddingModel({"models": {"embedding_backend": "auto", "embedding_device": "auto"}})
    monkeypatch.setattr(
        "local_ai_hub.embeddings.automatic_embedding_candidates",
        lambda _config: [("sentence-transformers", "cuda:0")],
    )

    assert embedding._candidate_specs() == [
        ("sentence-transformers", "cuda:0"),
        ("sentence-transformers", "cpu"),
    ]


def test_explicit_openvino_embedding_cpu_fallback_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_ai_hub.embeddings.openvino_device_candidates", lambda *_args: ["NPU"])
    strict = EmbeddingModel({"models": {"embedding_backend": "openvino", "embedding_device": "NPU"}})
    fallback = EmbeddingModel({
        "models": {"embedding_backend": "openvino", "embedding_device": "NPU"},
        "openvino": {"cpu_fallback": True},
    })

    assert strict._candidate_specs() == [("openvino", "NPU")]
    assert fallback._candidate_specs() == [("openvino", "NPU"), ("sentence-transformers", "cpu")]


def test_explicit_openvino_reranker_cpu_fallback_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("local_ai_hub.reranker.openvino_device_candidates", lambda *_args: ["NPU"])
    strict = Reranker({"models": {"reranker_backend": "openvino", "reranker_device": "NPU"}})
    fallback = Reranker({
        "models": {"reranker_backend": "openvino", "reranker_device": "NPU"},
        "openvino": {"cpu_fallback": True},
    })

    assert strict._candidate_specs() == [("openvino", "NPU")]
    assert fallback._candidate_specs() == [("openvino", "NPU"), ("torch", "cpu")]


def test_embedding_status_exposes_fallback_reason(tmp_path: Path) -> None:
    embedding = EmbeddingModel({"server": {"state_dir": str(tmp_path)}})
    embedding._fallback_reason = "OpenVINO/NPU model load failed"

    assert embedding.status()["fallback_reason"] == "OpenVINO/NPU model load failed"


def test_reranker_status_exposes_fallback_reason(tmp_path: Path) -> None:
    reranker = Reranker({"server": {"state_dir": str(tmp_path)}})
    reranker._fallback_reason = "OpenVINO/NPU model load failed"

    assert reranker.status()["fallback_reason"] == "OpenVINO/NPU model load failed"


def test_accelerator_status_reports_explicit_backend_and_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accelerators, "openvino_runtime", lambda: {"available": False, "devices": []})
    monkeypatch.setattr(accelerators, "openvino_device_candidates", lambda *_args: ["NPU"])
    monkeypatch.setattr(accelerators, "automatic_embedding_candidates", lambda _config: [("openvino", "NPU")])
    monkeypatch.setattr(accelerators, "_onnx_providers", lambda: set())
    monkeypatch.setattr(accelerators, "_torch_gpu_route", lambda: None)

    status = accelerator_status({
        "models": {
            "embedding_backend": "sentence-transformers", "embedding_device": "cuda",
            "reranker_backend": "torch", "reranker_device": "cpu",
        },
    })

    assert status["embedding"]["candidates"] == [("sentence-transformers", "cuda")]
    assert status["reranker"]["candidates"] == [("torch", "cpu")]


def test_accelerator_status_respects_auto_device_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accelerators, "openvino_runtime", lambda: {"available": False, "devices": []})
    monkeypatch.setattr(accelerators, "openvino_device_candidates", lambda *_args: ["NPU"])
    monkeypatch.setattr(accelerators, "automatic_embedding_candidates", lambda _config: [("openvino", "NPU")])
    monkeypatch.setattr(accelerators, "_onnx_providers", lambda: set())
    monkeypatch.setattr(accelerators, "_torch_gpu_route", lambda: None)

    status = accelerator_status({
        "models": {
            "embedding_backend": "auto", "embedding_device": "cpu",
            "reranker_backend": "auto", "reranker_device": "cpu",
        },
    })

    assert status["embedding"]["candidates"] == [("sentence-transformers", "cpu")]
    assert status["reranker"]["candidates"] == [("torch", "cpu")]


@pytest.mark.parametrize(
    ("backend", "device", "openvino_config", "expected_fallback"),
    [
        ("torch", "cuda", None, False),
        ("auto", "auto", None, True),
        ("torch", "cpu", None, True),
        ("openvino", "NPU", None, False),
        ("openvino", "NPU", {"cpu_fallback": True}, True),
    ],
)
def test_reranker_default_cpu_fallback_matches_route_policy(
    tmp_path: Path, backend: str, device: str,
    openvino_config: dict[str, bool] | None, expected_fallback: bool,
) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "models": {"reranker_backend": backend, "reranker_device": device},
    }
    if openvino_config is not None:
        config["openvino"] = openvino_config
    reranker = Reranker(config)
    captured: dict[str, object] = {}
    reranker._needs_gpu_admission = lambda: False
    reranker._rerank_without_admission = lambda *_args, **kwargs: (
        captured.update(kwargs) or {"success": True, "results": []}
    )

    assert reranker.rerank("query", ["document"])["success"] is True
    assert captured["allow_cpu_fallback"] is expected_fallback
