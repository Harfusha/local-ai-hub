import json
import math
from contextlib import closing

import pytest

import local_ai_hub.rag as rag_module
from local_ai_hub.rag import RAGStore


class _Embeddings:
    space_id = "centroid-test-space"

    def embed(self, texts, tenant, **kwargs):
        return {
            "success": True,
            "embeddings": [[1.0, 0.0] for _ in texts],
            "embedding_space_id": self.space_id,
        }


def _store(tmp_path):
    return _store_with_embeddings(tmp_path, _Embeddings())


def _store_with_embeddings(tmp_path, embeddings):
    return RAGStore(
        {"server": {"state_dir": str(tmp_path)}, "models": {"embedding_dimension": 2}},
        embeddings,
    )


def _seed_direction_clusters(store, cluster_count=200, rows_per_cluster=60, embedding_space=None, path_prefix="cluster"):
    tenant = store._scope_key("tenant-a")
    with closing(store._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                (
                    tenant,
                    "workspace-a",
                    f"{path_prefix}/cluster-{cluster:03d}/chunk-{row:03d}.txt",
                    0,
                    f"hash-{cluster}-{row}",
                    f"cluster {cluster} item {row}",
                    json.dumps(
                        [math.cos(2 * math.pi * cluster / cluster_count),
                         math.sin(2 * math.pi * cluster / cluster_count)]
                    ),
                    embedding_space or _Embeddings.space_id,
                )
                for cluster in range(cluster_count)
                for row in range(rows_per_cluster)
            ),
        )
        con.commit()


def test_centroid_filter_is_opt_in_and_preserves_fine_scoring(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _seed_direction_clusters(store)
    total_chunks = 200 * 60
    fine_scored_rows = []
    build_count = []
    original_score = getattr(rag_module, "_fine_cosine_scores", None)
    assert callable(original_score), "search must expose the real fine-scoring stage"

    def count_fine_scores(matrix, query_vector):
        fine_scored_rows.append(len(matrix))
        return original_score(matrix, query_vector)

    original_build = store._build_centroid_index

    def count_build(*args, **kwargs):
        build_count.append(1)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(rag_module, "_fine_cosine_scores", count_fine_scores)
    monkeypatch.setattr(store, "_build_centroid_index", count_build)
    exact_result = store.search("nearest vector exact", "tenant-a", "workspace-a", top_k=1, use_reranker=False)
    exact_scored = sum(fine_scored_rows)
    fine_scored_rows.clear()

    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_ENABLED", True)
    result = store.search("nearest vector", "tenant-a", "workspace-a", top_k=1, use_reranker=False)
    first_scored = sum(fine_scored_rows)
    fine_scored_rows.clear()
    warm_result = store.search("nearest vector warm", "tenant-a", "workspace-a", top_k=1, use_reranker=False)

    assert exact_result["success"] is True
    assert exact_result["results"][0]["path"] == "cluster/cluster-000/chunk-000.txt"
    assert exact_scored == total_chunks
    assert result["success"] is True
    assert result["results"][0]["path"] == "cluster/cluster-000/chunk-000.txt"
    assert warm_result["success"] is True
    assert warm_result["results"][0]["path"] == "cluster/cluster-000/chunk-000.txt"
    assert first_scored <= total_chunks // 10
    assert sum(fine_scored_rows) <= total_chunks // 10
    assert len(build_count) == 1


@pytest.mark.parametrize("threshold", [9999, 10000, 10001])
def test_production_threshold_is_ten_thousand_chunks(threshold):
    assert rag_module._centroid_threshold_reached(threshold) is (threshold > 10000)


def test_small_workspace_keeps_exact_scoring(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_MIN_CHUNKS", 100)
    store = _store(tmp_path)
    _seed_direction_clusters(store, cluster_count=20, rows_per_cluster=5)
    scored_rows = []
    original_score = rag_module._fine_cosine_scores

    def count_scores(matrix, query_vector):
        scored_rows.append(len(matrix))
        return original_score(matrix, query_vector)

    monkeypatch.setattr(rag_module, "_fine_cosine_scores", count_scores)
    result = store.search("nearest vector", "tenant-a", "workspace-a", top_k=1, use_reranker=False)

    assert result["success"] is True
    assert sum(scored_rows) == 100


def test_unavailable_numpy_falls_back_to_exact_scoring(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_MIN_CHUNKS", 100)
    store = _store(tmp_path)
    _seed_direction_clusters(store, cluster_count=20, rows_per_cluster=6)
    original_import = rag_module.importlib.import_module
    scored_rows = []
    original_score = rag_module._fine_cosine_scores

    def unavailable_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy unavailable for centroid build")
        return original_import(name, *args, **kwargs)

    def count_scores(matrix, query_vector):
        scored_rows.append(len(matrix))
        return original_score(matrix, query_vector)

    monkeypatch.setattr(rag_module.importlib, "import_module", unavailable_numpy)
    monkeypatch.setattr(rag_module, "_fine_cosine_scores", count_scores)
    result = store.search("nearest vector", "tenant-a", "workspace-a", top_k=1, use_reranker=False)

    assert result["success"] is True
    assert sum(scored_rows) == 120


def test_generation_change_rebuilds_cached_centroids(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_MIN_CHUNKS", 100)
    store = _store(tmp_path)
    _seed_direction_clusters(store, cluster_count=20, rows_per_cluster=6)
    scope_key = store._scope_key("tenant-a")
    first = store._centroid_index_for_search(scope_key, "workspace-a", _Embeddings.space_id, [1.0, 0.0])
    assert first is not None
    generation_before = first[0]

    other_store = _store_with_embeddings(tmp_path, _Embeddings())
    with closing(other_store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (scope_key, "workspace-a", "cluster-000/new.txt", 0, "new-hash", "new nearest", "[1.0,0.0]", _Embeddings.space_id),
        )
        generation_after = other_store._bump_workspace_index_generation(con, scope_key, "workspace-a")
        con.commit()

    second = store._centroid_index_for_search(scope_key, "workspace-a", _Embeddings.space_id, [1.0, 0.0])
    assert second is not None
    assert generation_after > generation_before
    assert second[0] == generation_after
    assert ("cluster-000/new.txt", 0) in second[1]


def test_candidate_filter_keeps_embedding_space_and_scope_path_filters(tmp_path, monkeypatch):
    # Keep this security-boundary case on the exact path so it proves the normal
    # SQL filters remain in force independently of centroid candidate selection.
    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_MIN_CHUNKS", 1000)
    embeddings = _Embeddings()
    embeddings.space_id = "space-a"
    store = _store_with_embeddings(tmp_path, embeddings)
    _seed_direction_clusters(store, cluster_count=20, rows_per_cluster=6, embedding_space="space-a")
    _seed_direction_clusters(
        store, cluster_count=20, rows_per_cluster=6,
        embedding_space="space-a", path_prefix="00-outside",
    )
    _seed_direction_clusters(
        store, cluster_count=20, rows_per_cluster=6,
        embedding_space="space-b", path_prefix="allowed/00-space-b",
    )
    tenant = store._scope_key("tenant-a")
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (tenant, "workspace-a", "outside/best.txt", 0, "other-space", "outside best", "[1.0,0.0]", "space-b"),
        )
        con.execute(
            "UPDATE chunks SET path='allowed/' || path WHERE tenant=? AND workspace=? AND embedding_space=? AND path LIKE 'cluster/%'",
            (tenant, "workspace-a", "space-a"),
        )
        con.commit()

    result = store.search(
        "nearest vector", "tenant-a", "workspace-a", top_k=1,
        use_reranker=False, scope_path="allowed",
    )
    assert result["success"] is True
    assert result["results"][0]["path"] == "allowed/cluster/cluster-000/chunk-000.txt"
    assert "space-b" not in result["results"][0]["path"]


def test_large_scoped_query_keeps_nearest_outside_global_probe_buckets(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_MIN_CHUNKS", 1000)
    store = _store(tmp_path)
    _seed_direction_clusters(
        store, cluster_count=200, rows_per_cluster=60,
        path_prefix="a-outside",
    )
    tenant = store._scope_key("tenant-a")
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO chunks(tenant,workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (tenant, "workspace-a", "z-allowed/nearest.txt", 0, "allowed-nearest", "scoped nearest", "[-1.0,0.0]", _Embeddings.space_id),
        )
        con.commit()

    result = store.search(
        "nearest vector", "tenant-a", "workspace-a", top_k=1,
        use_reranker=False, scope_path="z-allowed",
    )
    assert result["success"] is True
    assert result["results"][0]["path"] == "z-allowed/nearest.txt"


def test_read_uncertainty_uses_exact_search_without_cold_centroid_build(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_MIN_CHUNKS", 1000)
    store = _store(tmp_path)
    _seed_direction_clusters(store, cluster_count=20, rows_per_cluster=60)
    tenant = store._scope_key("tenant-a")
    with closing(store._connect()) as con:
        store._update_workspace_read_uncertainty(
            con, tenant, "workspace-a", uncertain_paths={"unrelated/missing.txt"},
        )
        con.commit()

    build_count = []
    original_build = store._build_centroid_index

    def count_build(*args, **kwargs):
        build_count.append(True)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(store, "_build_centroid_index", count_build)
    result = store.search(
        "nearest vector", "tenant-a", "workspace-a", top_k=1,
        use_reranker=False,
    )
    assert result["success"] is True
    assert result["results"][0]["path"] == "cluster/cluster-000/chunk-000.txt"
    assert build_count == []


def test_corrupt_vectors_fall_back_to_exact_search(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_module, "_CENTROID_FILTER_MIN_CHUNKS", 100)
    store = _store(tmp_path)
    _seed_direction_clusters(store, cluster_count=20, rows_per_cluster=6)
    scored_rows = []
    original_score = rag_module._fine_cosine_scores

    def count_scores(matrix, query_vector):
        scored_rows.append(len(matrix))
        return original_score(matrix, query_vector)

    monkeypatch.setattr(rag_module, "_fine_cosine_scores", count_scores)
    with closing(store._connect()) as con:
        con.execute(
            "UPDATE chunks SET embedding='not-json' WHERE path='cluster/cluster-000/chunk-000.txt'"
        )
        con.commit()

    result = store.search("nearest vector", "tenant-a", "workspace-a", top_k=1, use_reranker=False)
    assert result["success"] is True
    assert sum(scored_rows) == 120
