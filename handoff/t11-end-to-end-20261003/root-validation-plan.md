# T11 root validation plan — 2026-10-03

- Root HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Root not modified by T11.
- `rag.py` current preimage SHA-256 `88836FE1782A3D01ED3606BC8DD2FCCC40168AC4411C7CFB73B67DA802933C27`. Minimal `_index_locked` patch SHA-256 `FD69872676AC0929EBE573597374357BAA078B2B6FDB251F8338A6BFDB331E67`, apply-check PASS, unapplied.
- `index_paths_step()` initializes `embedding_space` before first record; no source-level UnboundLocalError found.
- Historical candidate suite: **183 passed, 3 skipped, 42.04 s**. It predates root integration.

## Focused root regressions — not run

- `tests/test_rag_hybrid.py::test_index_embeds_changed_chunks_without_undefined_text_list`
- `tests/test_rag_hybrid.py::test_index_paths_step_sets_embedding_space_before_nonempty_records`

## Root offline acceptance — not run

`python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_read_bounds.py tests/test_rag_fragment_cache.py tests/test_rag_hybrid.py tests/test_rag_quality_contract.py tests/test_rag_dedup.py tests/test_t11_project_policy_consumers.py tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_reranker_cache_identity.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_model_release_lifecycle.py`

## Bounded synthetic CPU measurements — not run

- `tests/test_rag_quality_contract.py::test_retrieval_latency_and_peak_memory_baseline`, set `RAG_BENCHMARK=1` — synthetic CPU retrieval; 1k/16k/100k vector rows; bounded batch-size matrix
- `tests/test_t11_rag_seed_integrity.py::test_t11_ingestion_batch_benchmark`, set `T11_RAG_BENCHMARK=1` — synthetic ingestion/seed CPU benchmark; fake embedder

T01 validation slot remains active. No tests/benchmarks run. No live model/GPU benchmark planned.
