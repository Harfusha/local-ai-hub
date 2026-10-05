# T11 RAG acceptance handoff — 2026-10-01

## Scope and ownership

- T11 candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`
- Candidate HEAD observed: `3c7da92aa6a267c2a18af0555d927f0e67d4c476`
- Root integration target: `C:\Users\Adam\.local-ai-hub` (T20 owns root)
- Latest focused candidate batches passed `11/11` in `10.82s` and `4/4` in `0.88s`; paired golden selector reran after exact-parity assertions and passed `1/1` in `0.38s`. Baseline and candidate rankings match on same dataset revision and exact `quality-space`; recall@10 and nDCG@10 both equal `1.0`. This proves parity, not improvement. T20 reports `66 passed, 1 skipped in 23.22s` for four root modules; its post-fix hard-ignore selector remains T20-owned.
- Preserve dirty candidate RAG tests. `src/local_ai_hub/project_config.py` is untracked and outside T11 scope; do not include it.

## Acceptance evidence already present

- Candidate offline focused batch was previously reported as `140 passed, 3 skipped in 28.55s`; not rerun here. Skips were live Ollama, ingestion benchmark, and 100k retrieval benchmark.
- Synthetic retrieval receipt: `handoff/t11-rag-benchmark-receipt.json`. 100k vectors, 384 dimensions, float32, 20 measured samples. Batch 4096 recorded p95 `302.532 ms`, peak traced memory `13.222 MiB`; acceptance target is warm RAG p95 <=750 ms. Candidate receipt only.
- Live reranker receipt: `handoff/t11-transformer-reranker-live-receipt.json`. Candidate selector passed `1 passed in 23.47s`; assertions include embedded/reranked true, degraded false, fallback null. Candidate runtime only; not root/install acceptance.
- Source tests cover bounded publish retry without re-embedding, disk-full/FTS failure, read uncertainty preserving stored snapshots while suppressing unverified results, config-change cache invalidation, hard-ignore and project-policy pruning, real same-HEAD Git seed validation, local worktree config reindex, exact embedding-space isolation, and paired golden relevance. Relevant focused selectors ran this turn.
- T11 release lifecycle receipt is separate: `tests/test_model_release_lifecycle.py` previously passed `7`; fake Torch/weakrefs prove Python reference release and best-effort cache calls, not physical VRAM reclamation.

## Acceptance still open

- Root-current integration and test receipt remain T20 responsibilities. Candidate evidence does not establish root, installed Hub, or deployment acceptance.
- Root-source overlay reproduced one RED: explicit `index_paths_step` retained a file under `rag.ignore_dirs`. Matching source fix is now present in T20 root; reverse apply-check passes. Patch: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-root-current-bounded-ingestion-production.patch`.
- Candidate hard-ignore cleanup, policy negatives, bounded reads and stale-result suppression, tenant isolation, embedding recovery, real same-HEAD seed integrity, local-config reindex and cache invalidation pass. Root post-fix validation remains T20-owned.
- Large benchmarks remain deferred. Paired golden quality ran CPU-only; no GPU/model work ran.
- Repeat live Ollama/reranker selector only after model slot is explicitly available. Preserve fresh receipt and process cleanup evidence.

## Commands queued for after T02

From candidate root `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_storage_service_reliability.py tests/test_reranker_cache_identity.py tests/test_rag_quality_contract.py tests/test_rag_hybrid.py tests/test_rag_fragment_cache.py tests/test_rag_dedup.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py
```

Run benchmarks serially, after focused suite:

```powershell
$env:T11_RAG_BENCHMARK='1'; python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_seed_integrity.py::test_t11_ingestion_batch_benchmark
$env:RAG_BENCHMARK='1'; python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_rag_quality_contract.py::test_retrieval_latency_and_peak_memory_baseline
```

Live model selector; run only after explicit model-slot availability:

```powershell
$env:T11_REAL_OLLAMA='1'; $env:T11_REAL_RERANKER='1'; python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_ingestion_contract.py::test_t11_live_ollama_rag_ingest_and_reranker_truthfulness
```

## T11 handoff artifacts

- Root-current release lifecycle patch: `handoff/t11-root-current-release-lifecycle.patch` (SHA-256 `37F30878FC5685C366D1407D79C828EB77DC2FE5D28712BD403A000CC4C00B39`); root `git apply --check` passed. Contains only `embeddings.py`, `reranker.py`, and `test_model_release_lifecycle.py`.
- Existing scoped RAG patches and receipts remain under `handoff/t11-*.patch` and `handoff/t11-*-receipt.json`; review each patch individually against current root. Do not apply whole worktree or unrelated dirty hunks.
