from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from types import TracebackType
from typing import Any

from local_ai_hub.reranker import Reranker


class _FairTestLock:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._owner: int | None = None
        self._waiters: list[int] = []
        self.waiter_queued = threading.Event()

    def __enter__(self) -> _FairTestLock:
        identity = threading.get_ident()
        with self._condition:
            if self._owner is not None:
                self._waiters.append(identity)
                self.waiter_queued.set()
            while self._owner is not None or (self._waiters and self._waiters[0] != identity):
                self._condition.wait()
            if self._waiters and self._waiters[0] == identity:
                self._waiters.pop(0)
            self._owner = identity
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        with self._condition:
            self._owner = None
            self._condition.notify_all()


class _OpenCpuGate:
    def slot(self, priority: int) -> Any:
        return nullcontext()


class _InterleavingModel:
    def __init__(self, lock: _FairTestLock) -> None:
        self.lock = lock
        self.first_a = threading.Event()
        self.calls: list[list[str]] = []

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> list[float]:
        docs = [doc for _query, doc in pairs]
        self.calls.append(docs)
        if docs and docs[0] == "A0":
            self.first_a.set()
            assert self.lock.waiter_queued.wait(timeout=3)
        return [0.5] * len(pairs)


def test_concurrent_reranks_interleave_between_two_pair_micro_batches(tmp_path: Path) -> None:
    reranker = Reranker({
        "server": {"state_dir": str(tmp_path)},
        "models": {"reranker": "fake-reranker", "reranker_device": "cpu"},
        "features": {"reranker": True},
        "cpu_retrieval": {"reranker_batch_size": 16},
        "cache": {"reranker": False},
    })
    lock = _FairTestLock()
    model = _InterleavingModel(lock)
    reranker._predict_lock = lock
    reranker._cpu_gate = _OpenCpuGate()
    reranker._model = model
    reranker._ensure_model = lambda **kwargs: True
    reranker._candidate_specs = lambda: []
    reranker._execution_identity = lambda: "test-model"
    reranker._cache_identity = lambda **kwargs: None

    with ThreadPoolExecutor(max_workers=2) as pool:
        request_a = pool.submit(reranker.rerank, "query-a", [f"A{i}" for i in range(4)])
        assert model.first_a.wait(timeout=3)
        request_b = pool.submit(reranker.rerank, "query-b", ["B0"])
        assert lock.waiter_queued.wait(timeout=3)
        result_b = request_b.result(timeout=5)
        result_a = request_a.result(timeout=5)

    assert result_a["success"] is True
    assert result_b["success"] is True
    assert all(len(batch) <= 2 for batch in model.calls)
    assert model.calls[0] == ["A0", "A1"]
    assert model.calls[1] == ["B0"]
