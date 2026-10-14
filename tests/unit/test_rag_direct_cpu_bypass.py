import json
from contextlib import closing

from local_ai_hub.rag import RAGStore


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

    def rerank(self, query, texts, top_k, priority):
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
