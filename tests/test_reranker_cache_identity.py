from __future__ import annotations

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
