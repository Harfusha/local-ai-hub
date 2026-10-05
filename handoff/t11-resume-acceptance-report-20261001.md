# T11 resumed acceptance — 2026-10-01

## Ownership and inherited state

- Candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`, HEAD `3c7da92aa6a267c2a18af0555d927f0e67d4c476`.
- At resume, candidate already had 13 top-level dirty entries: 10 modified files and 3 untracked entries (`handoff/`, `src/local_ai_hub/project_config.py`, `tests/test_rag_read_bounds.py`). Inventory: `handoff/t11-resume-inventory-20261001.json`.
- All those entries were inherited. This continuation changed only `src/local_ai_hub/rag.py` and `tests/test_t11_project_policy_consumers.py`, plus new handoff receipts in the existing untracked `handoff/` directory.
- `src/local_ai_hub/project_config.py` is inherited T21 boundary; left untouched. Root `C:\Users\Adam\.local-ai-hub` is T20-owned; no root edits.

## Resumed delta

- Fixed inherited incremental retry path referencing `uncertain_retry_paths` before loading it. Three current regressions failed with `NameError`; one workspace-state read was added to the existing SQLite read block. The three focused regressions then passed: `3 passed in 1.54s`.
- Added `test_explicit_rag_ingestion_normalizes_windows_path_before_policy_and_storage`. It passes a Windows-style relative path, checks project-policy acceptance, and asserts canonical `private/keep.py` storage with exact source text.
- Candidate delta: `handoff/t11-resume-acceptance-v1.patch`, SHA-256 `a5f885cc87927b44e45fcced8d780417de74df7f042728e6aa5fe0c0db85d804`. It applies cleanly to reconstructed pre-resume source/test snapshots. Pre-resume and current hashes are in inventory.
- `git diff --check` passed for both changed files.

## Current candidate acceptance

Exact command:

```powershell
python -m pytest -q --tb=short tests/test_rag_read_bounds.py tests/test_rag_fragment_cache.py tests/test_rag_hybrid.py tests/test_rag_quality_contract.py tests/test_rag_dedup.py tests/test_t11_project_policy_consumers.py tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_reranker_cache_identity.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_model_release_lifecycle.py
```

Result: `175 passed, 3 skipped in 33.02s`. Skips require live Ollama, the ingestion batch benchmark, and the 100k retrieval benchmark.

Coverage includes exact tenant/workspace/embedding-space filtering and reuse, legacy space recovery, bounded reads and unreadable-path suppression/retry, atomic SQLite/FTS publish failure handling, SVG/diagram ingestion contracts, project-policy pruning and cache invalidation, linked-worktree config consumer behavior, reranker truthfulness/cache identity, and paired retrieval relevance.

Windows separator consumer selector passed separately: `1 passed in 0.33s`. The paired golden test passed within the full suite: six relevant credential sources above 58 distractors, exact `quality-space`, Recall@10 `1.0`, nDCG@10 `1.0` for paired baseline/candidate indexes.

## Current-source performance evidence

- Receipt: `handoff/t11-resume-rag-16k-perf-receipt-20261001.json`.
- Current RAG source SHA-256: `db181093f53f0d6666a890413bfea5f52359890ce8236def0160df744cf0c6ff`.
- Current benchmark harness SHA-256: `81c17571143a4256cf9d9a9017137b82cfd564cd4f45b21e48e5f3fbecba7a3c`.
- Deterministic CPU fixture: 16,384 rows × 384 dimensions, float32, seed 41. Two warmups and five timed samples per batch size. `tracemalloc` ran separately from timing.
- Batch 2048: median `55.722 ms`, p95 `56.527 ms`, peak traced `9.975 MiB`. A separate complexity probe scored all 16,384 rows in 8 batches, maximum 2048 rows; expected top result remained first.
- The older 81-test/100k×384 p95 `504.122 ms` receipt and later `302.532 ms` receipt lack current source/harness fingerprints and predate current source/harness mtimes. Treat both as historical, not current acceptance. No 100k, GPU, or live-model run occurred.

## Limits

- No production deployment or installed-instance proof.
- Live Ollama/reranker selector remains skipped in this run; the previous candidate live receipt is separate and not refreshed.
- Current 16k synthetic CPU measurement is fingerprinted. 100k performance on this resumed source remains unverified.
- Full Local AI Hub release gates remain T20 scope.

## Previous continuation checkpoint — 2026-10-01

- Initial dirty inventory preserved: the 10 modified files, untracked `handoff/`, `src/local_ai_hub/project_config.py`, and `tests/test_rag_read_bounds.py` were inherited. The project-config file remains T21-owned; root remains T20-owned. This continuation added only the negative benchmark evidence receipt and this checkpoint. No `/api/context/pack` or root file was edited.
- No active Codex goal existed (`get_goal` returned `null`); this existing T11 handoff is the updated checkpoint. State: **REVIEW / INCOMPLETE**, not done.
- Current RAG and benchmark-harness SHA-256 still match the fingerprints above (`db181093f53f0d6666a890413bfea5f52359890ce8236def0160df744cf0c6ff` and `81c17571143a4256cf9d9a9017137b82cfd564cd4f45b21e48e5f3fbecba7a3c`). After restoring the speculative batch-limit experiment, the exact configured-batch selector passed: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_quality_contract.py::test_search_uses_larger_bounded_vector_batches_when_configured` → `3 passed in 0.66s`. `git diff --check` passed.
- A fresh 100k run on the fingerprinted candidate failed: `RAG_BENCHMARK=1 python -B -m pytest -q -s --tb=short -p no:cacheprovider tests/test_rag_quality_contract.py::test_retrieval_latency_and_peak_memory_baseline` → `1 failed in 46.40s`, p95 `972.658 ms` at configured batch `4096` (limit `750 ms`). The later one-slot diagnostic run, while a temporary 12 MiB batch cap was present, failed at batch `512`, p95 `1698.727 ms` in `57.47s`; see `handoff/t11-rag-100k-red-20261001.json`. That experiment was reverted; its failing batch was below the altered memory cap. Do not rerun the benchmark under the current no-repeat instruction.
- The older `handoff/t11-rag-benchmark-receipt.json` is historical and has no current source/harness fingerprint. It cannot override the fresh RED. A post-run CPU snapshot showed 34% total CPU and `REANIMAL` at 6.9 GB working set, but this is not run-time telemetry and does not prove measurement contamination. No algorithmic cause is confirmed; performance acceptance remains open.
- The live Ollama ingestion/reranker selector separately passed `1 passed in 41.82s` on the candidate. GPU reranker acceptance remains blocked by missing local `BAAI/bge-reranker-base` weights; no network, install, or download was used. Root/install acceptance and T20's remaining root selector stay with T20.

## Latest continuation checkpoint — 2026-10-02

- Ownership was rechecked before edits. Existing dirty candidate files were inherited; `project_config.py` remains T21-owned, and root plus `/api/context/pack` remain outside this checkout's edit scope. No inherited T11 hunks were reverted.
- This continuation's source delta is confined to `src/local_ai_hub/rag.py` (SHA-256 `231ca7c6ba2af653eae20af1bc64bea949a028abbcee68cbff32838a42608c19`) and `tests/test_rag_hybrid.py` (SHA-256 `3d5865f6f278078af9391b946803d5f10ad57f83e95cc375ea889abe60f2bad9`), plus this checkpoint. Other dirty files remain inherited.
- Source-backed hot-path optimization: `_search_uncached` previously opened `BEGIN IMMEDIATE` for every resolved embedding-space search, including warm searches whose workspace metadata already matched. It now reads the stored identity first and takes the write lock only on mismatch, then rechecks under lock before updating. This removes an unnecessary writer lock from the common path and preserves race-safe metadata updates. It does not establish the cause of the 100k timing failures and is not claimed to improve measured p95.
- Added deterministic regression `tests/test_rag_hybrid.py::test_warm_search_skips_embedding_space_write_lock`. RED on the inherited code: warm query still issued `BEGIN IMMEDIATE`. GREEN with adjacent identity-transition tests: `3 passed in 0.57s`.
- Full offline T11 suite after the change:

  ```powershell
  python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_read_bounds.py tests/test_rag_fragment_cache.py tests/test_rag_hybrid.py tests/test_rag_quality_contract.py tests/test_rag_dedup.py tests/test_t11_project_policy_consumers.py tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_reranker_cache_identity.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_model_release_lifecycle.py
  ```

  Result: `176 passed, 3 skipped in 47.51s`. Skips are the 100k retrieval benchmark, live Ollama selector, and ingestion benchmark. `git diff --check` passed.
- Keep the recorded 100k RED and do not rerun without a T20 slot. The performance gate remains **REVIEW / OPEN**; the metadata lock optimization has functional proof only. GPU reranker weights and root/install acceptance remain external blockers. Do not mark T11 complete.

## T20 root-current overlay — 2026-10-02

- Root HEAD at overlay preparation: `01df56605ccf484ebfe2808ac60d696c4e81dffc`. Its working tree is T20-owned and dirty; no root write was made.
- Current root already contains the T11 production scope in `embeddings.py`, `rag.py`, and `reranker.py`. In particular, its `_search_uncached` has no search-time `BEGIN IMMEDIATE`; the candidate warm-search lock behavior is already present by a different implementation. Therefore source pre/post hashes are identical and the overlay does not transplant candidate files or unrelated inherited hunks.
- Root-current overlay patch adds only the T11 warm-search regression to `tests/test_rag_hybrid.py`: `handoff/t11-root-current-overlay-20261002.patch`, SHA-256 `910ff7dabf98202c2d7bc9b3c4fde1633377782c0493e869c1a164fa7009e145`. Read-only `git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-root-current-overlay-20261002.patch` passed against the current dirty root. No root test or apply was run.
- Per-file root pre/post SHA and ownership map are in `handoff/t11-root-current-overlay-20261002.json`. T21 `project_config.py` and `/api/context/pack` are excluded.
- Latest candidate offline T11 suite, using the root-compatible seeded-metadata form of the regression, passed `176 passed, 3 skipped in 39.49s`. Skips are 100k retrieval, live Ollama, and ingestion benchmark. No benchmark rerun; fresh 100k performance gate stays **REVIEW / OPEN** pending T20 slot.
