from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time

import pytest

from local_ai_hub.cache import stable_hash
from local_ai_hub.reranker import Reranker


class _RevisionedCrossEncoder:
    def __init__(self, revision: str | None, score: float):
        self.model = SimpleNamespace(config=SimpleNamespace(_commit_hash=revision))
        self.score = score
        self.predict_calls = 0

    def predict(self, pairs, **_kwargs):
        self.predict_calls += 1
        return [self.score for _ in pairs]


class _BlockingRevisionedCrossEncoder(_RevisionedCrossEncoder):
    def __init__(self, revision: str, score: float):
        super().__init__(revision, score)
        self.started = threading.Event()
        self.release = threading.Event()

    def predict(self, pairs, **_kwargs):
        self.predict_calls += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("timed out waiting to release reranker prediction")
        return [self.score for _ in pairs]


def _reranker(state_dir, model: _RevisionedCrossEncoder) -> Reranker:
    instance = Reranker({
        "server": {"state_dir": str(state_dir)},
        "models": {"reranker": "same-model", "reranker_backend": "torch", "reranker_device": "cpu"},
        "features": {"reranker": True},
        "cache": {"reranker": True},
    })
    instance._model = model
    instance.active_backend = "torch"
    instance.active_device = "cpu"
    return instance


def test_reranker_cache_separates_same_name_backend_device_by_loaded_revision(tmp_path):
    old_model = _RevisionedCrossEncoder("a" * 40, 0.15)
    new_model = _RevisionedCrossEncoder("b" * 40, 0.91)
    old = _reranker(tmp_path, old_model)
    new = _reranker(tmp_path, new_model)

    assert old.rerank("query", ["document"])["results"][0]["score"] == pytest.approx(0.15)
    result = new.rerank("query", ["document"])

    assert result["results"][0]["score"] == pytest.approx(0.91)
    assert result["cache_hits"] == 0
    assert new_model.predict_calls == 1


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("active_backend", "openvino"), ("active_device", "cuda")],
)
def test_reranker_cache_separates_backend_and_device(tmp_path, attribute, value):
    first_model = _RevisionedCrossEncoder("f" * 40, 0.2)
    second_model = _RevisionedCrossEncoder("f" * 40, 0.8)
    first = _reranker(tmp_path, first_model)
    second = _reranker(tmp_path, second_model)
    setattr(second, attribute, value)

    first.rerank("query", ["document"])
    result = second.rerank("query", ["document"])

    assert result["results"][0]["score"] == pytest.approx(0.8)
    assert result["cache_hits"] == 0
    assert second_model.predict_calls == 1


def test_concurrent_identical_rerank_requests_share_prediction(tmp_path):
    model = _BlockingRevisionedCrossEncoder("9" * 40, 0.63)
    reranker = _reranker(tmp_path, model)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(reranker.rerank, "query", ["document"])
        assert model.started.wait(timeout=1)
        second = pool.submit(reranker.rerank, "query", ["document"])
        deadline = time.monotonic() + 1
        while reranker.flight_group.coalesced_calls == 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        try:
            assert reranker.flight_group.coalesced_calls == 1
        finally:
            model.release.set()
        first_result, second_result = first.result(timeout=2), second.result(timeout=2)

    assert first_result["results"] == second_result["results"]
    assert model.predict_calls == 1


def test_reranker_bypasses_cache_when_loaded_revision_is_unknown(tmp_path):
    first_model = _RevisionedCrossEncoder(None, 0.2)
    second_model = _RevisionedCrossEncoder(None, 0.8)
    first = _reranker(tmp_path, first_model)
    second = _reranker(tmp_path, second_model)

    first.rerank("query", ["document"])
    result = second.rerank("query", ["document"])

    assert result["results"][0]["score"] == pytest.approx(0.8)
    assert result["cache_hits"] == 0
    assert second_model.predict_calls == 1


def test_reranker_cache_separates_max_length(tmp_path):
    model = _RevisionedCrossEncoder("c" * 40, 0.75)
    first = _reranker(tmp_path, model)
    second_model = _RevisionedCrossEncoder("c" * 40, 0.25)
    second = _reranker(tmp_path, second_model)
    second.max_length += 128

    first.rerank("query", ["document"])
    result = second.rerank("query", ["document"])

    assert result["results"][0]["score"] == pytest.approx(0.25)
    assert result["cache_hits"] == 0
    assert second_model.predict_calls == 1


def test_reranker_recomputes_nonfinite_cache_score(tmp_path):
    model = _RevisionedCrossEncoder("d" * 40, 0.8)
    reranker = _reranker(tmp_path, model)
    key = stable_hash({"identity": reranker._cache_identity(), "q": "query", "d": "document"})
    reranker.cache.set(key, float("nan"))

    result = reranker.rerank("query", ["document"])

    assert result["results"][0]["score"] == pytest.approx(0.8)
    assert result["cache_hits"] == 0
    assert model.predict_calls == 1


def test_reranker_does_not_cache_nonfinite_prediction(tmp_path):
    model = _RevisionedCrossEncoder("e" * 40, float("nan"))
    reranker = _reranker(tmp_path, model)
    key = stable_hash({"identity": reranker._cache_identity(), "q": "query", "d": "document"})

    result = reranker.rerank("query", ["document"])

    assert result["success"] is False
    assert "invalid" in result["error"]
    assert reranker.cache.get(key) is None
