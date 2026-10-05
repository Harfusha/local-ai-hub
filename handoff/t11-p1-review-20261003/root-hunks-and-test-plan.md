# T11 P1 patch review and test plan — 2026-10-03

Read-only review. No source or root edits. No test or benchmark run.

## Patch and receipt

- Candidate patch SHA-256: `ECB3FB752A3ADE63D7F77B6166DA9189350CAAC3BC2240C21BFF694EBD856955`.
- `rag.py` absent from patch. This avoids the previously identified dangling `changed_texts` guard and missing `embedding_space` initialization in partial merge.
- Included patch paths: src/local_ai_hub/embeddings.py, src/local_ai_hub/reranker.py, tests/test_rag_fragment_cache.py, tests/test_rag_hybrid.py, tests/test_rag_quality_contract.py.
- Current root preimages match previous receipt: `True`. Read-only `git apply --check --recount`: `pass`.
- Independent review JSON: `handoff/t11-p1-review-20261003/review.json`.

## P1 checks

- T11 `index()` lines 901-949: `changed_indices` drives candidate selection and embedding batches; no `changed_texts` reference remains. Check: `False`.
- T11 `index_paths_step()` lines 1302-1700: `embedding_space` initialized before `records.append`. Check: `True`.
- Current root `index()` keeps `changed_texts` declaration, population, dedup reassignment, and guard together. Check: `False`.
- Current root path-step initializes embedding space before records. Check: `True`.
- Therefore P1 fixes are present in both candidate source and untouched root preimage. Risk was introduced only by partial root patch; keep `rag.py` excluded until its related logic is reconciled as whole method-level hunks.

## Root-current hunk plan

1. Keep root `index()` hunk atomic from `changed_indices` / `changed_texts` initialization through dedup result reassignment and the embedding guard/batch loop. Never accept removal of `changed_texts` producers while retaining `if changed_texts`; candidate refactor must switch the guard and every dependent path to `changed_indices` in one reviewed hunk.
2. Keep root `index_paths_step()` hunk atomic from `configured_space`/identity resolution through `embedding_space` fallback and first record construction. Required invariant: assignment occurs before any `records.append` path. Do not split configuration from the stored-space fallback.
3. Current root preimage already satisfies both runtime invariants. No corrective root hunk is needed until integration of T11's broader RAG changes is approved. Existing safe patch omits `rag.py`.

## Test plan after T04 releases validation window

1. Run focused regressions:
   `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_hybrid.py::test_index_embeds_changed_chunks_without_undefined_text_list tests/test_rag_hybrid.py::test_index_paths_step_sets_embedding_space_before_nonempty_records`
2. Run exact T11 offline acceptance suite:
   `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_rag_read_bounds.py tests/test_rag_fragment_cache.py tests/test_rag_hybrid.py tests/test_rag_quality_contract.py tests/test_rag_dedup.py tests/test_t11_project_policy_consumers.py tests/test_t11_rag_ingestion_contract.py tests/test_t11_rag_seed_integrity.py tests/test_reranker_cache_identity.py tests/test_embedding_cache.py tests/test_embedding_batch_deduplication.py tests/test_model_release_lifecycle.py`
3. Do not run benchmark/live selectors under this plan. T11 live reranker, Ollama, and GPU metrics remain unverified.

T04 was still active when this plan was recorded. Run no validation until its release is confirmed.
