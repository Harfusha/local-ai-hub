from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

import pytest

from local_ai_hub.reranker import Reranker


class _RevisionedCrossEncoder:
    def __init__(self, revision: str | None, score: float):
        self.model = SimpleNamespace(config=SimpleNamespace(_commit_hash=revision))
        self.score = score
        self.predict_calls = 0

    def predict(self, pairs, **_kwargs):
        self.predict_calls += 1
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


@pytest.mark.parametrize(
    "scores",
    [
        [0.1, 0.2],
        [float("nan")],
        [True],
    ],
    ids=["extra-score", "nan-score", "boolean-score"],
)
def test_reranker_rejects_invalid_prediction_scores(tmp_path, scores):
    model = _RevisionedCrossEncoder("c" * 40, 0.5)
    model.predict = lambda _pairs, **_kwargs: scores
    reranker = _reranker(tmp_path, model)

    result = reranker.rerank("query", ["document"])

    assert result["success"] is False
    assert result["results"] == []
    assert result["error"]


def test_identical_concurrent_rerank_calls_share_execution_and_copy_results(tmp_path):
    model = _RevisionedCrossEncoder("d" * 40, 0.5)
    reranker = _reranker(tmp_path, model)
    prediction_started = threading.Event()
    release_prediction = threading.Event()
    prediction_calls = 0

    def predict(pairs, **_kwargs):
        nonlocal prediction_calls
        prediction_calls += 1
        prediction_started.set()
        assert release_prediction.wait(timeout=2)
        return [0.5 for _ in pairs]

    model.predict = predict
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(reranker.rerank, "query", ["document"])
        assert prediction_started.wait(timeout=1)
        second = pool.submit(reranker.rerank, "query", ["document"])
        deadline = time.monotonic() + 1
        try:
            while reranker.flight_group.coalesced_calls == 0 and time.monotonic() < deadline:
                time.sleep(0.001)
            assert reranker.flight_group.coalesced_calls == 1
        finally:
            release_prediction.set()
        first_result = first.result(timeout=2)
        second_result = second.result(timeout=2)

    assert prediction_calls == 1
    assert first_result["success"] is True
    assert second_result["success"] is True
    second_result["results"][0]["score"] = 0.9
    assert first_result["results"][0]["score"] == pytest.approx(0.5)
