# T10 impact/performance acceptance + root review — 2026-10-02

## Result

Read-only review only; no root writes, tests, or benchmark. Root `git diff --check` over T10/mixed paths exited 0. Root/candidate selector receipts remain separate: candidate six-module suite was **30 passed in 4.81s**; this is not root acceptance. Current root source/test hashes and exact command are pinned in the JSON manifest.

## Root delta ownership

- **T10 in `code_index.py`:** `analyzer_version` schema/cache guard; parser-version reindex; fallback call ownership; stale rename/delete edge cleanup; forced fresh reads; query cache invalidation; callers/callees restricted to call edges.
- **T10 in `repo_tools.py`:** snapshot/hash cache invalidation and forced verification; bounded Python fallback with separate `python_fallback_max_files` and `python_fallback_files_scanned`; explicit accelerator failure.
- **T10 in `preprocess.py`:** two invalidate-before-hash sites only (around root lines 1961-1964 and 2254-2257). Other hunks remain with their owners.
- **T10 in `retrieval.py`:** bounded backend weight overrides; exact root hash pinned. Defaults are byte-equal, SHA-256 `418B6299…A502D57B`.
- **T21-owned / exclude:** `project_config.py`, `services.py`, `tool_agent.py`, `docs/PROJECT_CONFIGURATION.md`, `tests/test_project_path_hints.py`, `tests/test_t21_root_path_hint_worktree_chain.py`, `tests/test_t21_search_recall.py`. Also T21 path-policy/project-settings/search-path hunks inside mixed `repo_tools.py`; do not move that whole file as a T10 patch.

No source defect was established by this static pass. Mixed ownership and unrun root selectors are the review limits.

## Exact T10 impact acceptance

1. Freshness: same-size/same-mtime changes are re-read; analyzer-version changes reindex; stale derived schema rebuild preserves durable `agent_state.sqlite3` bytes.
2. Graph: exact expected caller/target edges appear through SQLite and callers/callees; non-call edges excluded; supported parser and built-in fallbacks covered.
3. Rename/delete: no stale file, symbol, ref, or edge rows remain.
4. Impact: known changed leaf reaches expected caller chain and exact affected test; chunking/query caps hold; truncation cannot pass as complete success.
5. Retrieval: exact evidence and backend/fallback/freshness/coverage/truncation status; timeout/crash/malformed optional backend must degrade explicitly.
6. Policy: deny/exclude/outside-root tests plus default-scope positive case; hints only prioritize.

Root test command after T20 grants the exclusive slot:

```powershell
$env:PYTHONPATH='C:\Users\Adam\.local-ai-hub\src'; python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_ast_impact_acceptance.py tests/test_t10_code_index_schema_rebuild.py tests/test_t10_fallback_callgraph_parity.py tests/test_t10_python_fallback_budget.py tests/test_t10_repo_search_path_hints.py tests/test_t10_retrieval_fixture_matrix.py tests/test_adaptive_retrieval.py tests/test_repo_topology.py tests/test_affected_tests.py tests/test_cross_repo_federation.py
```

Not run. First rehash manifest paths and assert `local_ai_hub.__file__` points into root `src`.

## Exact performance acceptance

The existing root `tools/benchmark_surfaces.py --full-matrix` covers six pairs from file sizes `{100, 10000, 100000}` × RAG sizes `{10000, 100000}`. T10 large rows: `(100000,10000)` and `(100000,100000)`. Use plan-grade `--light-repetitions 1000 --comparison-repetitions 30 --concurrency 1 4 16 32`, cold and warm. Record stage p50/p95/p99, throughput, failures, response bytes, quality, source/config/hardware/workload fingerprints. Pair exact baseline/candidate with candidate `--compare-with <baseline-matrix.json>`.

```powershell
python -B tools/benchmark_surfaces.py --state-dir <BASELINE_STATE_OUTSIDE_REPO> --full-matrix --light-repetitions 1000 --comparison-repetitions 30 --concurrency 1 4 16 32 --timeout-seconds 3600
python -B tools/benchmark_surfaces.py --state-dir <CANDIDATE_STATE_OUTSIDE_REPO> --full-matrix --light-repetitions 1000 --comparison-repetitions 30 --concurrency 1 4 16 32 --timeout-seconds 3600 --compare-with <BASELINE_MATRIX_JSON>
```

Templates only; no run. T02 still owns source-pin reconciliation/slot. **Harness gap:** comparison stages contain `hub_code_index`, callers, and callees, but no dedicated impact latency stage; `affected_tests` is only a quality golden. T02/T20 must add/authorize explicit impact measurement. Do not claim impact performance without it.

Measure/report `peak_rss_bytes` separately from latency; harness defines RSS as process lifetime high-water mark. Do not use tracemalloc as substitute. T10 goldens (`symbols`, `graph`, `affected_tests`, `retrieval_relevance`) must pass. Master plan blocks unexplained >10% latency regressions and requires >=25% p95 or peak-memory improvement for optimization claims at equal quality. Its 300ms warm indexed lookup budget is specified for 10k files only; no 100k p95 target is invented here.

## Current blocker

T02's partial `-04` is not a valid pair; T02 reported slot `-05` transferred to T11. T20 has not released an exclusive slot to T10. T19 clean-host install/release and integrated T20 release remain open. No test/benchmark was run for this handoff.


## Slot and T02 coordination update

T02 reports its first full baseline matrix ended incomplete; partial `-04` is preserved and `-05` remains a proposal awaiting T20 approval. No paired receipt. T11 is active and asking T20 for slot 11. T20 idle status is not a slot grant. T10 has asked T02 whether it will add a dedicated impact latency stage and for authoritative command/pins; response pending. T10 will not duplicate or edit the T02 harness and has run no new tests/benchmark.


## T02 coordination response

T02 plans its own dedicated `hub_impact_latency` comparison stage; `affected_tests` stays a separate correctness golden. T10 must not duplicate or edit the harness. T02 has no new benchmark slot; T20 is waiting for Hub health and review of a new manifest/pins. The old `-05` is only a proposal; refresh harness hash after implementation. T02 prepare command: `python tools/run_t02_paired_matrix.py prepare --manifest <NEW_MANIFEST>`. Measurement gate: `measurement_allowed=true`, `pending=[]`, and an explicitly assigned new slot. Partial `-04` is not reusable.


## T20 serial queue update

T02 confirmed it owns the planned `hub_impact_latency` stage; T10 will not duplicate the harness. T20 queue: T11 slot 11, T05 slot 12, T03 slot 13, T08 at/after slot 14, then T10 pending prioritization. No T10 slot yet; no tests/benchmark run. T02 measurement still requires fresh approved manifest/pins, `measurement_allowed=true`, `pending=[]`, and assigned slot.


## Resume recheck

Candidate T10 six-module receipt remains **30 passed in 4.81s**; root remains untested. Root HEAD and 16 pinned source/test hashes rechecked with zero drift. T20 queue currently has T11 slot 11 awaiting broker/fresh pins, T05 next pending, T03 13, T08 14+, and T10 after queue/prioritization. No T10 test or benchmark launched.


## Latest queue state

T11 reports one native selector passed outside the assigned route; a subsequent offline suite was stopped and is incomplete/UNKNOWN. T20 requested the receipt and immediate slot release. No explicit T10 slot grant is visible; T10 launched no tests.
