import json
from contextlib import closing

from local_ai_hub.rag import RAGStore
import local_ai_hub.reranker as reranker_module
from local_ai_hub.reranker import Reranker


class _Embeddings:
    space_id = "direct-cpu-bypass-test"

    def embed(self, texts, tenant, **kwargs):
        return {
            "success": True,
            "embeddings": [[1.0, 0.0] for _ in texts],
            "embedding_space_id": self.space_id,
        }


class _RerankerSpy:
    def __init__(self, active_device):
        self.active_device = active_device
        self.device = active_device
        self.calls = 0

    def rerank(self, query, texts, top_k, priority, allow_cpu_fallback=True):
        self.calls += 1
        return {
            "success": True,
            "results": [
                {"index": index, "score": float(len(texts) - index)}
                for index in reversed(range(len(texts)))
            ][:top_k],
        }


def _store_with_two_chunks(tmp_path):
    store = RAGStore(
        {
            "server": {"state_dir": str(tmp_path)},
            "features": {"reranker": True},
            "models": {"embedding_dimension": 2},
        },
        _Embeddings(),
    )
    tenant = store._scope_key("tenant-a")
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (tenant, "workspace-a", f"doc-{index}.txt", 0, f"hash-{index}",
                 f"candidate {index}", json.dumps([1.0, 0.0]), _Embeddings.space_id)
                for index in range(2)
            ],
        )
        con.commit()
    return store


class _StubPredictor:
    def __init__(self, device, fail=False, cpu_predictions=None):
        self.device = device
        self.fail = fail
        self.cpu_predictions = cpu_predictions

    def predict(self, pairs, **kwargs):
        if self.fail:
            raise RuntimeError("stub accelerator prediction failure")
        if self.device == "cpu" and self.cpu_predictions is not None:
            self.cpu_predictions.append(len(pairs))
        return [0.25 for _ in pairs]


def _stub_openvino_reranker(tmp_path, monkeypatch, *, fail_gpu_load, fail_gpu_predict):
    reranker = Reranker(
        {
            "server": {"state_dir": str(tmp_path)},
            "features": {"reranker": True},
            "models": {"reranker_backend": "openvino", "reranker_device": "GPU"},
            "openvino": {"cpu_fallback": True},
        }
    )
    monkeypatch.setattr(reranker_module, "openvino_device_candidates", lambda config, device: ["GPU"])
    attempts = []
    cpu_predictions = []

    def load_candidate(index):
        candidates = reranker._candidate_specs()
        backend, device = candidates[index]
        attempts.append((backend, device))
        reranker._candidates = candidates
        reranker._candidate_index = index
        if backend == "openvino" and fail_gpu_load:
            reranker._model = None
            reranker.active_backend = None
            reranker.active_device = None
            return False
        reranker._model = _StubPredictor(
            device,
            fail=backend == "openvino" and fail_gpu_predict,
            cpu_predictions=cpu_predictions,
        )
        reranker.active_backend = backend
        reranker.active_device = device
        reranker._load_error = None
        return True

    monkeypatch.setattr(reranker, "_load_candidate", load_candidate)
    return reranker, attempts, cpu_predictions


def test_direct_rag_route_blocks_cpu_candidate_after_cold_gpu_load_failure(tmp_path, monkeypatch):
    store = _store_with_two_chunks(tmp_path / "rag")
    reranker, attempts, cpu_predictions = _stub_openvino_reranker(
        tmp_path / "reranker", monkeypatch, fail_gpu_load=True, fail_gpu_predict=False
    )
    store.reranker = reranker

    baseline = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=False)
    result = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=True)

    assert attempts == [("openvino", "GPU")]
    assert cpu_predictions == []
    assert [item["path"] for item in result["results"]] == [item["path"] for item in baseline["results"]]


def test_direct_rag_route_blocks_cpu_candidate_after_gpu_prediction_failure(tmp_path, monkeypatch):
    store = _store_with_two_chunks(tmp_path / "rag")
    reranker, attempts, cpu_predictions = _stub_openvino_reranker(
        tmp_path / "reranker", monkeypatch, fail_gpu_load=False, fail_gpu_predict=True
    )
    store.reranker = reranker

    baseline = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=False)
    result = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=True)

    assert attempts == [("openvino", "GPU")]
    assert cpu_predictions == []
    assert [item["path"] for item in result["results"]] == [item["path"] for item in baseline["results"]]


def test_non_rag_reranker_call_keeps_cpu_fallback_by_default(tmp_path, monkeypatch):
    reranker, attempts, cpu_predictions = _stub_openvino_reranker(
        tmp_path, monkeypatch, fail_gpu_load=True, fail_gpu_predict=False
    )

    result = reranker.rerank("candidate", ["first", "second"], top_k=2)

    assert result["success"] is True
    assert attempts == [("openvino", "GPU"), ("torch", "cpu")]
    assert cpu_predictions == [2]


def test_non_rag_reranker_runtime_failure_keeps_cpu_fallback_by_default(tmp_path, monkeypatch):
    reranker, attempts, cpu_predictions = _stub_openvino_reranker(
        tmp_path, monkeypatch, fail_gpu_load=False, fail_gpu_predict=True
    )

    result = reranker.rerank("candidate", ["first", "second"], top_k=2)

    assert result["success"] is True
    assert attempts == [("openvino", "GPU"), ("torch", "cpu")]
    assert cpu_predictions == [2, 2]


def test_direct_search_bypasses_active_cpu_reranker_and_preserves_candidates(tmp_path):
    store = _store_with_two_chunks(tmp_path)
    reranker = _RerankerSpy("cpu")
    store.reranker = reranker

    baseline = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=False)
    result = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=True)

    assert reranker.calls == 0
    assert [item["path"] for item in result["results"]] == [item["path"] for item in baseline["results"]]


def test_direct_search_still_uses_active_gpu_reranker(tmp_path):
    store = _store_with_two_chunks(tmp_path)
    reranker = _RerankerSpy("cuda:0")
    store.reranker = reranker

    baseline = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=False)
    result = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=True)

    assert reranker.calls == 1
    assert [item["path"] for item in result["results"]] == list(reversed([item["path"] for item in baseline["results"]]))


def test_direct_search_does_not_load_cold_cpu_reranker(tmp_path):
    store = _store_with_two_chunks(tmp_path)
    reranker = _RerankerSpy(None)
    reranker.device = "cpu"
    store.reranker = reranker

    store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=True)

    assert reranker.calls == 0


def test_direct_search_keeps_lazy_gpu_reranking(tmp_path):
    store = _store_with_two_chunks(tmp_path)
    reranker = _RerankerSpy(None)
    reranker.device = "cuda:0"
    store.reranker = reranker

    baseline = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=False)
    result = store._search_uncached("candidate", "tenant-a", "workspace-a", top_k=2, use_reranker=True)

    assert reranker.calls == 1
    assert [item["path"] for item in result["results"]] == list(reversed([item["path"] for item in baseline["results"]]))
