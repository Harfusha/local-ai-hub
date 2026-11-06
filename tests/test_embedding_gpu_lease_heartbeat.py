from __future__ import annotations

import threading
import time

from local_ai_hub.cache import SingleFlightGroup
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore


class _Cache:
    def get_many(self, keys):
        return {}

    def set_many(self, _values):
        return None


def test_embedding_renews_gpu_fence_until_long_inference_finishes(tmp_path, monkeypatch):
    model = EmbeddingModel.__new__(EmbeddingModel)
    model.config = {"models": {"embedding": "test", "embedding_backend": "sentence-transformers"}}
    model.model_name = "test"
    model.backend = "sentence-transformers"
    model.device = "cuda"
    model.active_backend = None
    model.active_device = "cpu"
    model._active_cache_identity = "sentence-transformers:cuda:test"
    model._active_embedding_dimension = 2
    model._ollama_model_name = "test"
    model.cache = _Cache()
    model.cache_enabled = False
    model.flight_group = SingleFlightGroup(shards=1, default_timeout_seconds=2)
    model._execution_local = threading.local()
    model._gpu_reservation_path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(model._gpu_reservation_path, ttl_seconds=0.12)
    model._gpu_reservation_store = store
    observation = {}
    original_renew = store.renew
    renewals = 0

    def track_renewal(*args, **kwargs):
        nonlocal renewals
        renewed = original_renew(*args, **kwargs)
        if renewed:
            renewals += 1
        return renewed

    store.renew = track_renewal

    def long_inference(_texts, **_kwargs):
        before = renewals
        time.sleep(0.3)
        active = store.read()
        observation["active"] = active
        observation["renewals_during_inference"] = renewals - before
        return {"success": True, "embeddings": [[1.0, 0.0]]}

    model._encode_request_key = lambda _texts, _query: "long-inference"
    model._encode_uncached = long_inference
    monkeypatch.setattr("local_ai_hub.embeddings.uses_torch_cuda", lambda *_args: True)

    result = model.encode(["slow query"], query=True)

    assert result["success"] is True
    assert observation["active"] is not None
    assert observation["active"]["state"] == "active"
    assert observation["renewals_during_inference"] >= 1
    assert store.read() is None
