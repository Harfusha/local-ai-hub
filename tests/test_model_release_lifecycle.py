from __future__ import annotations

import gc
import sys
import threading
import types
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.reranker import Reranker


class FakeTorch(types.ModuleType):
    def __init__(self):
        super().__init__("torch")
        self.empty_cache_calls = 0
        self.synchronize_calls = 0
        self.cuda = types.SimpleNamespace(
            empty_cache=self.empty_cache, synchronize=self.synchronize
        )

    def empty_cache(self):
        self.empty_cache_calls += 1

    def synchronize(self):
        self.synchronize_calls += 1

    @staticmethod
    def get_num_threads():
        return 2

    @staticmethod
    def set_num_threads(_count):
        return None


class FakeEncoder:
    def __init__(self, entered=None, resume=None):
        self.max_seq_length = 128
        self.prompts = {}
        self.entered = entered
        self.resume = resume

    def encode(self, texts, **_kwargs):
        if self.entered is not None:
            self.entered.set()
            assert self.resume.wait(timeout=5)
        return [[float(len(text)), 1.0] for text in texts]


class FakeCrossEncoder:
    def __init__(self, entered=None, resume=None):
        self.entered = entered
        self.resume = resume

    def predict(self, pairs, **_kwargs):
        if self.entered is not None:
            self.entered.set()
            assert self.resume.wait(timeout=5)
        return [0.5 for _ in pairs]


def _install_fake_backends(monkeypatch: pytest.MonkeyPatch, *, encoder=None, cross_encoder=None):
    torch = FakeTorch()
    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = lambda *_args, **_kwargs: encoder or FakeEncoder()
    sentence_transformers.CrossEncoder = lambda *_args, **_kwargs: cross_encoder or FakeCrossEncoder()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)
    return torch


def _config(state_dir: Path) -> dict:
    return {
        "server": {"state_dir": str(state_dir)},
        "models": {
            "embedding": "fake-embedding",
            "embedding_backend": "sentence-transformers",
            "embedding_device": "cuda:0",
            "reranker": "fake-reranker",
            "reranker_backend": "torch",
            "reranker_device": "cuda:0",
        },
    }


def _load_cuda_models(config: dict, embedding=None, reranker=None):
    embedding = embedding or EmbeddingModel(config)
    reranker = reranker or Reranker(config)
    embedding._candidate_specs = lambda **_kwargs: [("sentence-transformers", "cuda:0")]
    reranker._candidate_specs = lambda: [("torch", "cuda:0")]
    assert embedding._load_candidate(0)
    assert reranker._load_candidate(0)
    return embedding, reranker


def test_embedding_release_waits_for_inference_and_cache_waits_for_other_cuda_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    entered = threading.Event()
    resume = threading.Event()
    encoder = FakeEncoder(entered, resume)
    torch = _install_fake_backends(monkeypatch, encoder=encoder)
    embedding, reranker = _load_cuda_models(_config(tmp_path / "state"))
    release_started = threading.Event()
    original_release = embedding.release

    def release_while_inference_runs():
        release_started.set()
        return original_release()

    monkeypatch.setattr(embedding, "release", release_while_inference_runs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        inference = pool.submit(embedding._encode_st_batch, ["active"], query=False, priority=1)
        assert entered.wait(timeout=5)
        release = pool.submit(embedding.release)
        assert release_started.wait(timeout=5)
        assert not release.done()
        assert torch.empty_cache_calls == 0

        resume.set()
        assert inference.result(timeout=5)[0] == [[6.0, 1.0]]
        release.result(timeout=5)

    assert embedding._model is None
    assert reranker._model is not None
    assert torch.empty_cache_calls == 0
    reranker.release()
    assert reranker._model is None
    assert torch.empty_cache_calls == 1
    assert torch.synchronize_calls == 1
    assert reranker.release() is False
    assert torch.empty_cache_calls == 1


def test_reranker_release_waits_for_inference_and_embedding_can_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    entered = threading.Event()
    resume = threading.Event()
    cross_encoder = FakeCrossEncoder(entered, resume)
    loads = {"embedding": 0}
    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = lambda *_args, **_kwargs: (
        loads.__setitem__("embedding", loads["embedding"] + 1) or FakeEncoder()
    )
    sentence_transformers.CrossEncoder = lambda *_args, **_kwargs: cross_encoder
    torch = FakeTorch()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)
    embedding, reranker = _load_cuda_models(_config(tmp_path / "state"))
    release_started = threading.Event()
    original_release = reranker.release

    def release_while_inference_runs():
        release_started.set()
        return original_release()

    monkeypatch.setattr(reranker, "release", release_while_inference_runs)

    with ThreadPoolExecutor(max_workers=2) as pool:
        inference = pool.submit(reranker._predict, [("query", "document")], priority=1)
        assert entered.wait(timeout=5)
        release = pool.submit(reranker.release)
        assert release_started.wait(timeout=5)
        assert not release.done()
        assert torch.empty_cache_calls == 0
        resume.set()
        assert inference.result(timeout=5) == [0.5]
        release.result(timeout=5)

    assert reranker._model is None
    assert embedding._model is not None
    assert torch.empty_cache_calls == 0
    assert reranker._predict([("query", "reload")], priority=1) == [0.5]
    assert reranker._model is not None
    assert torch.empty_cache_calls == 0
    reranker.release()

    embedding.release()
    assert torch.empty_cache_calls == 1
    assert torch.synchronize_calls == 1
    vectors, backend = embedding._encode_st_batch(["reload"], query=False, priority=1)
    assert vectors == [[6.0, 1.0]]
    assert backend == "sentence-transformers"
    assert loads["embedding"] == 2
    embedding.release()
    assert torch.empty_cache_calls == 2
    assert torch.synchronize_calls == 2


def test_non_cuda_backend_release_never_empties_cuda_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    torch = _install_fake_backends(monkeypatch)
    model = EmbeddingModel(_config(tmp_path / "state"))
    model._candidate_specs = lambda **_kwargs: [("openvino", "GPU")]
    assert model._load_candidate(0)

    model.release()

    assert model._model is None
    assert torch.empty_cache_calls == 0


def test_non_cuda_reranker_release_never_empties_cuda_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    torch = _install_fake_backends(monkeypatch)
    reranker = Reranker(_config(tmp_path / "state"))
    reranker._candidate_specs = lambda: [("openvino", "GPU")]
    assert reranker._load_candidate(0)

    reranker.release()

    assert reranker._model is None
    assert torch.empty_cache_calls == 0


def test_release_timeout_preserves_models_until_inference_can_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    torch = _install_fake_backends(monkeypatch)
    embedding, reranker = _load_cuda_models(_config(tmp_path / "state"))
    locked = threading.Event()
    unlock = threading.Event()

    def hold_release_locks():
        embedding._encoder_lock.acquire()
        reranker._predict_lock.acquire()
        locked.set()
        assert unlock.wait(timeout=5)
        reranker._predict_lock.release()
        embedding._encoder_lock.release()

    with ThreadPoolExecutor(max_workers=1) as pool:
        holder = pool.submit(hold_release_locks)
        assert locked.wait(timeout=5)
        assert embedding.release(timeout_seconds=0.01) is False
        assert reranker.release(timeout_seconds=0.01) is False
        assert embedding._model is not None
        assert reranker._model is not None
        assert torch.empty_cache_calls == 0
        unlock.set()
        holder.result(timeout=5)

    assert embedding.release()
    assert torch.empty_cache_calls == 0
    assert reranker.release()
    assert torch.empty_cache_calls == 1


def test_release_drops_last_strong_model_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    torch = _install_fake_backends(monkeypatch)
    embedding, reranker = _load_cuda_models(_config(tmp_path / "state"))
    embedding_model = weakref.ref(embedding._model)
    reranker_model = weakref.ref(reranker._model)

    assert embedding.release() is True
    assert embedding._model is None
    assert embedding.active_backend is None
    assert embedding.active_device is None
    gc.collect()
    assert embedding_model() is None
    assert torch.empty_cache_calls == 0

    assert reranker.release() is True
    assert reranker._model is None
    assert reranker.active_backend is None
    assert reranker.active_device is None
    gc.collect()
    assert reranker_model() is None
    assert torch.synchronize_calls == 1
    assert torch.empty_cache_calls == 1


def test_reranker_rechecks_model_after_release_races_with_prediction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cross_encoder = FakeCrossEncoder()
    torch = _install_fake_backends(monkeypatch, cross_encoder=cross_encoder)
    embedding, reranker = _load_cuda_models(_config(tmp_path / "state"))
    ensured = threading.Event()
    resume = threading.Event()
    original_ensure = reranker._ensure_model
    pause_once = {"pending": True}
    ensure_results = []

    def ensure_then_pause(*args, **kwargs):
        available = original_ensure(*args, **kwargs)
        ensure_results.append((available, reranker._model is not None, reranker._load_error))
        if pause_once["pending"]:
            pause_once["pending"] = False
            ensured.set()
            assert resume.wait(timeout=5)
        return available

    monkeypatch.setattr(reranker, "_ensure_model", ensure_then_pause)

    with ThreadPoolExecutor(max_workers=1) as pool:
        prediction = pool.submit(reranker._predict, [("query", "document")], priority=1)
        assert ensured.wait(timeout=5)
        assert reranker.release(timeout_seconds=0.1)
        assert reranker._model is None
        resume.set()
        result = prediction.result(timeout=5)
        assert result == [0.5], ensure_results

    assert reranker._model is not None
    assert torch.empty_cache_calls == 0
    reranker.release()
    assert torch.empty_cache_calls == 0
    embedding.release()
    assert torch.empty_cache_calls == 1
