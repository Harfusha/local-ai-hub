# T10 current candidate focused acceptance

- Date: 2026-10-01 (Europe/Prague).
- Candidate HEAD: `7a36be3b8b69531dccd9215515ac793369da0a44`.
- Candidate-scoped patch SHA-256: `9cc116c4a761374b98cae61577d3b41b6f9c8d194b4acd1b509ef1d445edc3fc` (357864 bytes).
- Candidate package source tree SHA-256: `cbe75a7e54743b49de7ffee932aaeeff0b939613014dbffdf57f64245fb682b6`.
- Benchmark input SHA-256: `14d8f89f98588fecc426cad129c70c979c473f9b69b065d2bb18a6b4c7c3c11c`.
- Scope: T10 worktree only; no root writes. T20 explicitly allowed isolated candidate pytest selectors.

```powershell
$env:PYTHONPATH='src'
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_t10_retrieval_edges.py::test_treesitter_extracts_direct_call_edges `
  tests/test_t10_retrieval_edges.py::test_code_index_finds_typescript_arrow_callers `
  tests/test_t10_retrieval_edges.py::test_call_edge_analyzer_version_rejects_stale_parse_blobs `
  tests/test_t10_acceptance.py::test_code_index_reindexes_unchanged_content_after_analyzer_version_change `
  tests/test_t10_acceptance.py::test_preprocessor_queues_unchanged_files_after_analyzer_version_change `
  tests/test_t10_acceptance.py::test_framework_fixtures_keep_only_real_call_edges `
  tests/test_t10_acceptance.py::test_fallback_parsers_mask_comments_and_literals_before_building_call_edges `
  tests/test_t10_retrieval_edges.py::test_deterministic_callers_intent_combines_direct_symbols_path_hints_and_ast_edges `
  tests/test_adaptive_retrieval.py::test_path_hints_rank_context_evidence_without_narrowing_lexical_search `
  tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_configured_ignored_directory `
  tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_configured_ignored_extension `
  tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_extension_outside_allowlist `
  tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_escape_repository_root `
  tests/test_adaptive_retrieval.py::test_ignored_directory_is_filtered_from_accelerated_search `
  tests/test_adaptive_retrieval.py::test_accelerated_search_rejects_candidates_outside_repository `
  tests/test_t10_retrieval_edges.py::test_call_graph_queries_report_truncation_and_unverified_freshness `
  tests/test_t10_retrieval_edges.py::test_call_graph_queries_honor_large_explicit_result_limits `
  tests/test_t10_retrieval_edges.py::test_impact_reports_dependent_coverage_and_truncation `
  tests/test_t10_retrieval_edges.py::test_impact_result_cache_reuses_warm_result_and_invalidates_after_index_update `
  tests/test_t10_retrieval_edges.py::test_impact_reports_exact_candidate_count_when_bounded_scan_truncates `
  tests/test_t10_benchmark.py::test_repository_benchmark_emits_symbol_search_and_concurrency_matrix `
  tests/test_t10_benchmark.py::test_benchmark_effective_impact_limit_matches_code_index_hard_cap `
  tests/test_performance.py::test_python_search_fallback_metric_is_separate_from_ripgrep_timeout
```

- Result: exit 0; 45 passed, 2 skipped in 3.09s.
- Skips: Java and C++ Tree-sitter parser unavailable.
- Root/current-source 100k candidate plus paired baseline benchmark: pending T20 exclusive CPU window. No benchmark run in this turn.
- Historical broad candidate receipt (216 passed, 2 skipped) is not substituted for current fingerprint evidence.


## Additional cache acceptance selectors

```powershell
$env:PYTHONPATH='src'
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_t10_acceptance.py::test_hash_cache_detects_same_size_rewrite_with_restored_mtime `
  tests/test_t10_acceptance.py::test_hash_only_revalidation_counts_same_stat_content_change `
  tests/test_t10_acceptance.py::test_code_index_update_detects_same_size_rewrite_with_restored_mtime `
  tests/test_t10_snapshot_cache_capacity.py
```

- Candidate result: exit 0; 5 passed in 0.77s.
- This does not include proposed root-only `tests/test_t10_snapshot_cache_revalidation.py`; that new test remains unrun.

## Additional T10 graph/preprocessor acceptance

```powershell
$env:PYTHONPATH='src'
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_affected_tests_no_code_index.py `
  tests/test_preprocess_operational_mode.py `
  tests/test_t10_transitive_dependencies.py
```

- Candidate result: exit 0; 8 passed in 1.32s.
- Covers transitive importers without CodeIndex, graph impact through symbol-free files, inexact-count/truncation reporting, and pause/resume scheduling behavior.

## CodeGraph removal and unsupported-parser fallback

```powershell
$env:PYTHONPATH='src'
python -B -m pytest -q -p no:cacheprovider --tb=short `
  tests/test_codegraph_package_policy.py `
  tests/test_t10_retrieval_edges.py::test_code_index_fallback_keeps_java_cpp_calls_with_degraded_parser_status
```

- Candidate result: exit 0; 8 passed in 2.75s.
- Six package-policy tests confirm removed managed CodeGraph/Kuzu integration, config/backend cleanup, packaging cleanliness, and retained native graph MCP route.
- Two Java/C++ fallback cases retain call edges and report parser status `parser_unavailable`; Tree-sitter skips in focused AST run remain expected grammar-availability skips.
- Root handoff: root already has `tests/test_codegraph_package_policy.py`; candidate-only `tests/test_t10_retrieval_edges.py` is absent there. No root write or test run in this receipt.

## Current targeted candidate aggregate

Unique selectors across the focused retrieval/parser set (45), cache set (5), graph/preprocessor set (8), CodeGraph/fallback set (8), and seven newly unique benchmark/retrieval selectors: **73 passed, 2 skipped**. The Java/C++ skips are Tree-sitter grammar availability; Java/C++ fallback cases passed separately. The standalone hash-only rerun and four overlapping selectors from the latest 11-test run are not counted again.

## Final focused receipt (2026-10-01)

- Earlier candidate-only command in `handoff/t10-final-acceptance-runbook-20261001.md`; exit 0, **11 passed in 1.61s**.
- Seven selectors were new relative to the aggregate above: deterministic RRF tie order, imported-source input fingerprint, external-baseline identity, untracked test fingerprint, path-hint metric/relevance, legacy impact cap, and legacy incomplete-coverage normalization.
- No 100k benchmark was run. The earlier 11-selector run released its slot to T20; a later user-directed focused consumer run is recorded below.

## Project-config consumer regressions (2026-10-01)

- Candidate-focused command in the runbook exited 0: **20 passed, 2 skipped in 12.53s**. Skips are unavailable Java/C++ Tree-sitter grammars.
- Live root overlay uses the actual dirty `project_config.py` (SHA-256 `4238b6a6de1de00f55f4679ce0df7d431522ec1bafabfa272258c1662f13f713`) and `services.py` (SHA-256 `a1ac60b4bf12cd656d8c5d277871b7ee6621e069c67af47f72793f72eecfb34f`); subprocess asserts both import paths and file hashes. It also proves repository search drops a prioritized excluded hint. Full receipt and exact command: `artifacts/t10-root-current-config-overlay-acceptance-20261001.md`.
- Regressions cover preprocess path exclusions and configured extension discovery, config-digest cache invalidation, configured project type/solution metadata in generated profiles, CodeIndex path/phase policy, language-override parser selection and reindex, call-graph/modules phase skips with durable resume, diagnostics phase preservation, and fingerprint coverage for the new regression file.
- T10 checkout lacks `project_config.py`; ordinary consumer tests inject its API contract. The isolated overlay tested inheritance and path-hint revision/config invalidation against the live root resolver. T20 still owns merging candidate work into root. No root writes or 100k benchmark.

## Root-current consumer patch regression update (2026-10-01)

- `tests/test_t10_project_config_consumers.py`: **5 passed in 6.16s** against the live root `project_config.py` and `services.py`. Root services live SHA-256 at test time: `1556edbe4336e1d0fecdac86d79593ab6f62be12a1f13841537cac453721dcc1`.
- Java/C++ capability selector `tests/test_t10_retrieval_edges.py::test_treesitter_extracts_direct_call_edges -k "java or cpp"`: **1 passed, 2 skipped, 8 deselected**. Both Tree-sitter grammars unavailable; fixtures remain. Generic fallback is not counted as Tree-sitter coverage.
- Receipt proves allowed lexical hint use; excluded hint denial; stale revision/config hint rejection; configured `.pyx` watcher admission/indexing; incremental exclusion cleanup; full-inventory fallback on config-file event; parent Gemini seed and linked diagnostics preservation.
- Source and test transplant boundaries: `handoff/t10-root-current-consumer-patch-20261001.md`. Root CodeIndex/Preprocessor integration still untested and T20-owned.

## Supported-language AST calls and no-Hub harness smoke (2026-10-01)

- Latest bounded candidate acceptance command after config-file full-inventory assertion: **21 passed, 2 skipped in 7.53s**. Skips are Java/C++ Tree-sitter capability outcomes.
- AST selector: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_treesitter_extracts_direct_call_edges -k "python or csharp or typescript or tsx or javascript or go or rust"`; exit 0, **9 passed, 2 deselected in 0.29s**. Java/C++ remain skipped; fixtures were not weakened.
- Benchmark harness smoke used 100 files and one sample per workload, fallback parser, output under `%TEMP%`; exit 0, 100/100 files and 100/100 caller edges. It did not start Hub or external code-intelligence backends. Temporary output was removed.
- This smoke checks harness operability only. Paired 100k benchmark remains pending T20's exclusive CPU slot.
