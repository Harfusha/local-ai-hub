# T11 RAG acceptance follow-up

Status: candidate fix verified; T20 has integrated matching root source. T11 made no root edits. One post-fix root selector receipt remains T20-owned.

## Ownership and source state

- T11 candidate: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`, HEAD `3c7da92aa6a267c2a18af0555d927f0e67d4c476`.
- Integration root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root already contains owner changes; keep integration with root owner.
- User approved reusing T21 checkout `C:\Users\Adam\.codex\worktrees\t21-project-config\.local-ai-hub` for T11. Candidate `src/local_ai_hub/project_config.py` now matches that checkout at SHA-256 `AFE88B0B2CDBDADF821A52EBF534CACACC1B16EED32EC918642CEB0A27B9D0AD`. Root copy differs (`6050453FA90C83F0282C4DD2588CAC4454B5187F9C85521CF7AABF089E41C832`); do not overwrite it. T11 only needs the existing `settings.max_file_size_bytes` contract.

## Candidate findings and changes

- Recovery: single known legacy embedding space is inferred and persisted; unresolved or mixed legacy vectors return `embedding_space_rebuild_required`. Existing coverage is in `tests/test_t11_rag_ingestion_contract.py`.
- Isolation: retrieval filters tenant, workspace, and exact embedding space. Reuse filters tenant and embedding space. Candidate regression `test_tenant_isolation_blocks_cross_tenant_chunk_reuse_and_search` covers cross-tenant data.
- Ingestion: bounded reads detect growth after `stat`. Read uncertainty preserves the prior database snapshot, marks the path untrusted, invalidates search cache, and excludes that path from vector, FTS, and token results until a successful retry. Deterministic oversize and explicit policy rejection still prune transactionally.
- Worktree evidence: a real same-HEAD linked worktree verifies committed-blob seed reuse, dirty-child invalidation, config-change cache invalidation, and full reindex after local `.local-ai.worktree.toml` size-policy change. HEAD stays unchanged.
- FTS: active publication writes FTS changes inside the snapshot transaction. Write failure rolls back the prior snapshot; existing regressions are `test_incremental_index_fts_write_failure_keeps_previous_snapshot` and its document-index counterpart.
- Benchmark: candidate receipt has 12 cases at 1,024 / 16,384 / 100,000 chunks, dimension 384, float32, 20 measured samples at 100k. 100k p95 is 353.797 / 318.885 / 302.532 / 349.721 ms for batches 512 / 2,048 / 4,096 / 8,192. Maximum traced peak is 13.222 MiB. These meet the 750 ms and 16 MiB targets in this candidate receipt; they are not root receipts.
- Historical candidate reports of 140 passing focused tests and one live reranker test remain separate receipts. Latest targeted batches passed `11/11` in `10.82s` and `4/4` in `0.88s`; paired golden test reran after stricter assertions and passed `1/1` in `0.38s`. Baseline and candidate use same dataset revision and exact `quality-space`; rankings match, recall@10 `1.0`, nDCG@10 `1.0`. This proves parity and quality, not improvement. No GPU, model, large benchmark, or root test ran.
- The tenant fixture now sets `rag.scope="tenant"` and indexes distinct tenant roots. The earlier shared-scope fixture correctly failed because shared mode intentionally uses `*` as its storage key; it did not demonstrate a retrieval leak.
- The read-bounds file had five passing tests before that fixture correction. The corrected tenant selector passed separately. Combined with the selectors above, these are focused candidate receipts, not a full suite.

## Root-current patches

Root source integration is T20-owned. The previous production patch passed `git apply --reverse --check` against root. This refreshed artifact also changes read-error cleanup semantics; root compatibility must be rechecked by T20. T20's test files are already added and owner-adjusted; do not reapply old test additions.

- `handoff/t11-root-current-bounded-ingestion.patch` — combined bounded-read implementation and regression test patch from the previous handoff. Do not apply before RED; its test addition is superseded by the test-first patch below.
- `handoff/t11-root-current-bounded-ingestion-production.patch` — prior bounded-read, explicit project-policy cleanup, and hard-ignore patch. It does not include new read-uncertainty retrieval suppression. Root integration remains T20-owned. SHA-256: `19688B4DCADBDD9919489D2997DEE84405A98A6A895773DA6E05ADE0B89D4F26`.
- `handoff/t11-root-current-benchmark-acceptance.patch` — replaces root's smaller three-sample benchmark with candidate 100k/p95/peak-memory acceptance harness. SHA-256: `18f60fa5094ca2c13f119454651e6ec7cfde6430f4a917323bd33592d4ee08bf`.
- Older `t11-root-current-benchmark-receipt.patch` does not apply to current root; use the new root-current acceptance patch instead.

## Validation queue after T02 releases slot

Run focused contract suite first:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_rag_read_bounds.py tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_storage_service_reliability.py tests/test_reranker_cache_identity.py tests/test_rag_quality_contract.py tests/test_rag_hybrid.py tests/test_rag_fragment_cache.py tests/test_rag_dedup.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py
```

Then run ingestion and 100k benchmarks sequentially:

```powershell
$env:T11_RAG_BENCHMARK='1'; python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_seed_integrity.py::test_t11_ingestion_batch_benchmark
$env:RAG_BENCHMARK='1'; python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_rag_quality_contract.py::test_retrieval_latency_and_peak_memory_baseline
```

Run live Ollama/Reranker test only after its model slot is explicitly released:

```powershell
$env:T11_REAL_OLLAMA='1'; $env:T11_REAL_RERANKER='1'; python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_ingestion_contract.py::test_t11_live_ollama_rag_ingest_and_reranker_truthfulness
```

Candidate benchmark and tests remain candidate-only until root owner applies patches and records fresh root receipts.

## Root-current acceptance audit

Reviewed root HEAD and its current dirty T11/T21 paths. No root writes or test runs occurred.

- Schema/reindex coverage exists in root: `test_legacy_chunks_schema_without_embedding_space_is_rebuilt`, `test_full_index_reembeds_unchanged_files_when_embedding_space_changes`, rebuild error-preservation cases, and exclusion/deletion cleanup for files and FTS.
- Worktree cache seeding coverage exists: parent seeding reuses only matching file-cache entries, never RAG hashes, and invalidates inherited state for dirty children. T21 linked-worktree configuration resolution is covered separately. No path-hint work was changed or repeated.
- Current RAG policy tests cover all three entrypoints for project exclusions, preprocess-only exclusions, and skipped RAG phase. Generic T21 tests cover custom extension classification, binary rejection, force-include precedence, file limits, and linked-worktree config resolution.
- Candidate RED reproduced before the fix: failed reads left old source facts searchable. Current focused verification passes the read-failure, config-change, exact-space, hard-ignore, FTS rollback, and paired-quality selectors. Failed paths retain DB snapshot but return no search facts until successful retry. Paired baseline/candidate rankings match exactly on one revision and one embedding space; recall@10 and nDCG@10 are both `1.0`.
- Root-source overlay originally passed eight extension, size, worktree-phase, and config-digest selectors, then reproduced the explicit `rag.ignore_dirs` RED. Evidence: `C:\Users\Adam\.codex\worktrees\t11-rag-recovery-v2\.local-ai-hub\handoff\t11-root-consumer-matrix-20261001.md`.
- T20 reported `66 passed, 1 skipped in 23.22s` across its four-module root matrix. Its delegation also identified the hard-ignore case as a separate RED. Current root contains the combined source patch and passes reverse apply-check; T20 still owns a dedicated post-fix selector receipt. The live Ollama skip is not model-quality proof.
- Test patch fixtures now use actual root API, `Path.open`, and on-disk `stat()` size (portable across Windows CRLF). Updated test patch SHA-256 values: `handoff/t11-root-current-policy-tests-red.patch` `948E2935B880B1D4335795E4EE210836CCDE46BBF101A139992CB8B4ED515A03`; consumer-matrix test patch `1D2D043647E1380D0552629F7DF4D95FD9F68967EFC7F2204C803B487CD90C36`. Root already has T20's adjusted tests; do not apply additions again.
- Previous root-current source patch remains `handoff/t11-root-current-bounded-ingestion-production.patch` (SHA-256 `19688B4DCADBDD9919489D2997DEE84405A98A6A895773DA6E05ADE0B89D4F26`). It bounds reads and handles policy cleanup. T20 must integrate and verify new read-uncertainty metadata, cache-generation invalidation, and retrieval suppression.
- Keep `index`, `index_step`, Gemini preprocessing, CodeGraph removal, and T21 search/path-hint code untouched. Do not rerun the 81-test suite or large benchmark without new evidence.

First root command after test patch is applied and T20 releases the slot; this does not rerun the 81-test suite or 100k benchmark:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_t11_rag_project_policy.py::test_rag_index_paths_respects_hard_ignored_directory_with_force_include tests/test_t11_rag_project_policy.py::test_rag_ingestion_applies_custom_extension_and_project_size_policy tests/test_rag_read_bounds.py tests/test_t11_embedding_space_reindex.py tests/test_t11_rag_seed_integrity.py::test_legacy_chunks_schema_without_embedding_space_is_rebuilt tests/test_t11_rag_seed_integrity.py::test_parent_seed_reuses_only_matching_file_cache_and_never_rag_hash tests/test_t11_rag_seed_integrity.py::test_parent_seed_rejects_same_size_dirty_child_and_stale_source_text tests/test_t11_rag_seed_integrity.py::test_parent_seed_invalidates_previously_inherited_state_for_dirty_child
```
