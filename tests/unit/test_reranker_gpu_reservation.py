from __future__ import annotations

import threading
import time

from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
import local_ai_hub.reranker as reranker_module
from local_ai_hub.reranker import Reranker


def _cuda_reranker(tmp_path, monkeypatch):
    reranker = Reranker({
        "server": {"state_dir": str(tmp_path)},
        "models": {"reranker_backend": "torch", "reranker_device": "cuda"},
    })
    reranker.active_backend = "torch"
    reranker.active_device = "cuda"
    monkeypatch.setattr(reranker_module, "uses_torch_cuda", lambda backend, device: str(device).lower() == "cuda")
    monkeypatch.setattr(reranker, "_ensure_model", lambda **_kwargs: True)
    monkeypatch.setattr(reranker, "_rerank_uncached", lambda *_args, **_kwargs: {"success": True, "results": []})
    return reranker


def test_cuda_reranker_uses_shared_gpu_reservation(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)

    result = reranker.rerank("query", ["document"])

    assert result["success"] is True
    assert not (tmp_path / "external-gpu-reservation").exists()
    assert not (tmp_path / "external-gpu-reservation.lease.json").exists()


def test_cuda_reranker_marks_shared_reservation_active_until_call_returns(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)
    store = ExternalGpuReservationStore(tmp_path / "external-gpu-reservation")
    started = threading.Event()
    finish = threading.Event()

    def hold_rerank(*_args, **_kwargs):
        started.set()
        assert finish.wait(2)
        return {"success": True, "results": []}

    reranker._rerank_uncached = hold_rerank
    worker = threading.Thread(target=reranker.rerank, args=("query", ["document"]))
    worker.start()
    try:
        assert started.wait(1)
        record = store.read()
        assert record is not None
        assert record["state"] == "active"
        assert store.reserve("b" * 64, owner="second-reranker") is None
    finally:
        finish.set()
        worker.join(2)
    assert not worker.is_alive()
    assert store.read() is None


def test_cuda_reranker_renews_shared_reservation_during_long_call(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)
    store = reranker._gpu_reservation_store
    store.ttl_seconds = 0.12
    observed = {}
    original_renew = store.renew
    renewals = 0

    def track_renewal(*args, **kwargs):
        nonlocal renewals
        renewed = original_renew(*args, **kwargs)
        if renewed:
            renewals += 1
        return renewed

    store.renew = track_renewal

    def hold_rerank(*_args, **_kwargs):
        before = renewals
        time.sleep(0.3)
        observed["lease"] = store.read()
        observed["renewals_during_call"] = renewals - before
        return {"success": True, "results": []}

    reranker._rerank_uncached = hold_rerank

    result = reranker.rerank("query", ["document"])

    assert result["success"] is True
    assert observed["lease"] is not None
    assert observed["renewals_during_call"] >= 1
    assert store.read() is None


def test_cuda_reranker_fails_closed_when_gpu_is_reserved(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)
    reservation = tmp_path / "external-gpu-reservation"
    reservation.write_text("a" * 64, encoding="ascii")

    result = reranker.rerank("query", ["document"])

    assert result["success"] is False
    assert result["error_code"] == "gpu_reserved"
    assert result["retryable"] is True
    assert reservation.read_text(encoding="ascii") == "a" * 64


def test_cuda_reranker_releases_its_idle_reservation_when_activation_fails(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)
    store = reranker._gpu_reservation_store
    write_metadata = store._write_metadata
    uncached_calls = []

    def fail_activation(record):
        if record.get("state") == "active":
            return False
        return write_metadata(record)

    monkeypatch.setattr(store, "_write_metadata", fail_activation)
    reranker._rerank_uncached = lambda *_args, **_kwargs: uncached_calls.append(True)

    result = reranker.rerank("query", ["document"])

    assert result["success"] is False
    assert result["error_code"] == "gpu_reserved"
    assert result["retryable"] is True
    assert uncached_calls == []
    assert store.read() is None


def test_cuda_reranker_releases_reservation_after_completed_failure(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)
    reranker._rerank_uncached = lambda *_args, **_kwargs: {"success": False, "error": "uncertain"}

    result = reranker.rerank("query", ["document"])

    assert result["success"] is False
    assert not (tmp_path / "external-gpu-reservation").exists()


def test_cuda_reranker_releases_reservation_when_call_raises(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)

    def raise_error(*_args, **_kwargs):
        raise RuntimeError("inference failed")

    reranker._rerank_uncached = raise_error

    try:
        reranker.rerank("query", ["document"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("reranker exception was swallowed")

    assert not (tmp_path / "external-gpu-reservation").exists()


def test_disabled_cuda_reranker_does_not_claim_gpu(tmp_path, monkeypatch):
    reranker = _cuda_reranker(tmp_path, monkeypatch)
    reranker.enabled = False

    result = reranker.rerank("query", ["document"])

    assert isinstance(result, dict)
    assert not (tmp_path / "external-gpu-reservation").exists()
