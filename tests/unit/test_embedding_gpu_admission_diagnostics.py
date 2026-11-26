from pathlib import Path

from local_ai_hub import embeddings
from local_ai_hub.embeddings import EmbeddingModel


def test_embedding_error_reports_why_gpu_capacity_telemetry_was_unavailable(tmp_path, monkeypatch):
    model = EmbeddingModel({
        "server": {"state_dir": str(tmp_path)},
        "models": {
            "embedding": "model",
            "embedding_backend": "sentence-transformers",
            "embedding_device": "cuda",
        },
        "cache": {"embeddings": False},
    })
    model._gpu_reservation_store = object()
    model._gpu_reservation_path = Path(tmp_path / "external-gpu-reservation")
    monkeypatch.setattr(model, "_candidate_specs", lambda **_kwargs: [("sentence-transformers", "cuda:0")])
    monkeypatch.setattr(embeddings, "uses_torch_cuda", lambda *_args: True)
    monkeypatch.setattr(
        "local_ai_hub.external_gpu_reservation.conservative_gpu_capacity_budget_bytes",
        lambda: None,
    )

    result = model.encode(["uncached"], query=True)

    assert result["success"] is False
    assert result["error_code"] == "gpu_reserved"
    assert result["gpu_admission_reason"] == "capacity_telemetry_unavailable"
