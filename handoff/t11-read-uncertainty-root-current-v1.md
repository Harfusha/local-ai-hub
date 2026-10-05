# T11 read uncertainty — root-current handoff v1

Immutable handoff created 2026-10-01. Root source and tests were not changed or run.

## Root preimages

Captured from T20 root `C:\Users\Adam\.local-ai-hub`:

- `src/local_ai_hub/rag.py` SHA-256 `23BEE629DA1B9F4BA555FE64D031701553118F4CC3B55D8421FDC8D3885626DE`
- `tests/test_rag_read_bounds.py` SHA-256 `6E6CE0F1E93114579F6E2BA16AA3231D806F69506CB4BE5E368622B0E6A57E7C`
- `tests/test_rag_fragment_cache.py` SHA-256 `A20136FF7EB60F7B85E15F0CA3C5AFDB50FE6E042D1F0BDEA16500D23E5C1623`

## Immutable patches

- Production: `t11-root-current-read-uncertainty-v1-production.patch`; SHA-256 `C5F02D68E371C38B853DDC1A4F329E82EDF916ED6E3BA916B6FF68F193615B0F`
- Tests: `t11-root-current-read-uncertainty-v1-tests.patch`; SHA-256 `92DF47AEC69807ACCB50689EDD99661969335E4E052E3CF4B6050CD869F8F361`
- Paired quality receipt: `t11-paired-golden-quality-v1.json`; SHA-256 `B31E1D82C013B54F6308CE8A8045768CE58C782D545350E1327D46D9932B468F`

Exact read-only root checks:

```powershell
git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-root-current-read-uncertainty-v1-production.patch
git -C C:\Users\Adam\.local-ai-hub apply --check C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub\handoff\t11-root-current-read-uncertainty-v1-tests.patch
```

Both returned exit 0. Checks made no root changes and ran no root tests.

Production patch marks unreadable paths uncertain, preserves committed file/chunk/FTS rows, bumps workspace generation, suppresses uncertain paths from vector/FTS/token results, and rechecks generation after cache lookup. Test patch covers sequential recovery and a cache-lookup race.

## Candidate receipts

- `python -m pytest -q --tb=short tests/test_rag_read_bounds.py tests/test_t11_project_policy_consumers.py::test_rag_reindexes_same_head_worktree_after_local_config_change tests/test_rag_quality_contract.py::test_golden_corpus_keeps_relevant_credentials_above_realistic_distractors tests/test_rag_hybrid.py::test_search_excludes_vectors_from_other_embedding_spaces tests/test_t11_project_policy_consumers.py::test_explicit_rag_ingestion_reconciles_hard_ignored_paths tests/test_t11_rag_ingestion_contract.py::test_incremental_index_fts_write_failure_keeps_previous_snapshot` — **11 passed in 10.82s**.
- `python -m pytest -q --tb=short tests/test_rag_hybrid.py::test_search_reports_degraded_when_index_has_no_matching_embedding_space tests/test_rag_hybrid.py::test_search_reports_pending_rebuild_for_partial_embedding_spaces tests/test_rag_hybrid.py::test_search_cache_key_tracks_runtime_embedding_space tests/test_t11_project_policy_consumers.py::test_rag_policy_change_invalidates_cached_search_results` — **4 passed in 0.88s**.
- `python -m pytest -q --tb=short tests/test_rag_fragment_cache.py::test_search_rechecks_generation_after_uncertain_source_read` — **1 passed in 0.75s**.
- Paired quality selector — **1 passed in 0.38s**. Same dataset revision `ce2f9e38eb084b906bb3b1d422f38316a648527f54819d9e4d3f9f53f8bb16cc`, exact embedding space `quality-space`, identical baseline/candidate top-10 order, recall@10 `1.0` and nDCG@10 `1.0`. Parity only; no improvement claim.

## T20 acceptance still required

Read-only source inspection found root `_search_uncached` vector query scoped by tenant and workspace without an `embedding_space` predicate; FTS query also lacks exact-space filtering. Candidate exact-space selector passes. This root isolation gap is outside these immutable v1 patches and remains T20-owned. Do not claim root acceptance until T20 resolves exact-space isolation, applies/reviews these patches, and records fresh root receipts.

No Local AI Hub, GPU, model, 100k benchmark, root test, root write, new worktree, or new chat was used.
