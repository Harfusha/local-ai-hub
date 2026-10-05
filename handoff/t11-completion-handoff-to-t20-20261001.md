# T11 completion handoff to T20 — 2026-10-01

## Ownership

- Candidate worktree: `C:\Users\Adam\.codex\worktrees\f678\.local-ai-hub`, HEAD `3c7da92aa6a267c2a18af0555d927f0e67d4c476`.
- Root `C:\Users\Adam\.local-ai-hub` remains T20-owned. T11 did not edit root.
- Preserve candidate dirty state. Do not transplant the whole worktree.
- Candidate `src/local_ai_hub/project_config.py` came from the user-approved existing T21 checkout. Do not replace T20's root copy; T21/T20 own that integration boundary.

## T11 implementation delivered

- `src/local_ai_hub/embeddings.py`, `src/local_ai_hub/reranker.py`: release clears strong model references; reranker synchronizes and releases CUDA cache best-effort after inference locks.
- `src/local_ai_hub/rag.py`: exact tenant/workspace/embedding-space isolation for search and reuse; legacy embedding-space recovery; tenant/search-cache identity and generation invalidation; bounded reads and ingestion; atomic publication and bounded retry; read uncertainty suppresses unverified vector, FTS, and token results until retry; policy/hard-ignore cleanup; incremental preemption and same-metadata uncertain-path retry.
- Candidate tests cover ingestion contracts, seed/cache invalidation, project policy, SVG/diagram metadata safety, rerank truthfulness, and paired retrieval quality.
- Root already had T11 production integration when last checked by T20. The remaining V5 delta below only strengthens one existing root legacy-space regression test.

## Candidate validation receipts

- Candidate RAG core (`test_rag_read_bounds.py`, `test_rag_fragment_cache.py`, `test_rag_hybrid.py`): `52 passed in 16.08s`.
- Candidate ingestion/policy/seed (`test_t11_project_policy_consumers.py`, `test_t11_rag_ingestion_contract.py`, `test_t11_rag_seed_integrity.py`): `63 passed, 2 skipped in 22.98s`. Skips require live Ollama and opt-in ingestion benchmark.
- Candidate embeddings/reranker/retrieval (`test_reranker_cache_identity.py`, `test_embedding_cache.py`, `test_embedding_batch_deduplication.py`, `test_rag_quality_contract.py`, `test_rag_dedup.py`): `53 passed, 1 skipped in 4.96s`. Skip is the opt-in 100k benchmark.
- Total distinct candidate selectors above: `168 passed, 3 skipped` across 11 files.
- Paired golden retrieval selector: `1 passed in 0.37s`; six relevant documents and 58 distractors, first result is the credential rotation runbook, Recall@10 and nDCG@10 are both 1.0, exact `quality-space` in both indexes. This is parity/quality evidence, not a measured improvement.
- Hybrid lexical/vector selector plus paired golden selector previously ran together: `2 passed in 0.64s`.
- Changed embedding-space/reuse selector across `index`, `index_paths_step`, and `index_step`: `1 passed in 0.93s`.
- Live reranker candidate receipt: `handoff/t11-transformer-reranker-live-receipt.json`, `1 passed in 23.47s`; `embedded=true`, `reranked=true`, `degraded=false`, `fallback=null`, expected top path. Prestarted server cleanup stopped owned Ollama/llama-server process tree. Candidate runtime only.
- Existing candidate synthetic 100k receipt: `handoff/t11-rag-benchmark-receipt.json`, p95 `302.532 ms`, traced peak `13.222 MiB`; historical candidate receipt, not rerun in this continuation.
- Candidate release lifecycle suite previously passed 7 tests. It proves Python reference release and best-effort cache calls, not physical VRAM reclamation.

## Root integration receipts reported by T20

- T20 reports its integrated T11 root RAG modules: `35/35` passed.
- T20 later reports four root modules: `66 passed, 1 skipped in 23.22s`.
- T20 owns those root commands, code, and receipts. No root commands or changes were made by T11 in this completion pass.
- Post-handoff root test hash changed from V5 pre-integration pin `811984...` to `5e8508f96b808a7369fa9e97617be359f7f23ea7a6213364eec71b99f5149160`; this exactly matches the fresh root-copy test file used for `35 passed in 8.61s`. Root RAG production hash remains `4c0ed5c52ec4cd9d82b41f0d6d2188812d607d1ce58c4ffea956d045fbb9048a`. T20 integrated V5 equivalent test hunk; no patch reapplication is needed.

## Exact remaining handoff

- `handoff/t11-pin-manifest-v5.json` pins the current root source/test snapshot and candidate artifacts. Manifest SHA-256: `395d2aa5d0e48de3e706a943493feaf16301266a02d52deddca25cd3463ad979`.
- `handoff/t11-root-current-rag-v5-legacy-space-test.patch` is test-only; SHA-256 `f13e2190012edd870c484c9eaa36502f48346f1b97961cdd6d89582d3a0af7e6`. Strict `git apply --check` against root passed. The patch was not applied. It decodes stored vectors and requires exact newly produced vector plus exact embedding-space ID in all three indexing entrypoints. If T20 already integrated the equivalent test, no action is needed.
- `handoff/t11-root-current-rag-v5-validation.md` records the fresh root-copy receipt: `35 passed in 8.61s`, plus the strict apply-check. Its SHA-256 is pinned in V5 manifest.
- V3 production and tests patches remain pinned in `handoff/t11-pin-manifest-v3.json`. V4 delta is immutable but targets a candidate snapshot and MUST NOT be applied to current root.
- `handoff/t11-pin-manifest-v6.json` supersedes V5 as the post-integration root snapshot pin. V5 remains immutable historical pre-integration evidence.
- Retrieval quality evidence: `handoff/t11-candidate-quality-ranking-evidence-20261001.md`, SHA-256 `c6ba3f6c9a2ddccd0fbbaecc5b95ca3d567f87ab8519be5aef6ce573a7998714`.

## Acceptance boundary

T11 candidate implementation, focused offline acceptance, live reranker receipt, paired retrieval quality, and T20-reported root integration suites have evidence. No new GPU/100k/live-model work ran in this continuation; existing 100k and live reranker receipts are candidate-only. Full release readiness is separate from T11: T20 still owns remaining cross-task gates, clean-host packaging/install proof, and release acceptance.
