# T10 final acceptance runbook

Date: 2026-10-01 (Europe/Prague)

## Current state

- Worktree: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`, branch `codex/t10-resume-20260926`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`.
- Root is T20-owned at `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. T10 made no root writes.
- Candidate focused acceptance receipt: `artifacts/t10-acceptance-current-focused-20261001.md`; prior aggregate 73 unique passed, 2 skipped; latest focused run 20 passed, 2 skipped.
- Live root overlay receipt: `artifacts/t10-root-current-config-overlay-acceptance-20261001.md`; import path and SHA asserted for root `project_config.py` and `services.py`, including an excluded-hint repository-search check.
- Candidate test process completed. Root integration belongs to T20. Latest thread snapshot: T20 active; T02 idle.
- Do not start paired 100k run until T20 assigns exclusive CPU window. T02 is not a blocker while idle.
- Harness no-Hub smoke passed at 100 files, fallback parser, one sample per workload. It reported 100 indexed files and 100 caller edges; this is harness evidence only, not 100k acceptance.

## Paired benchmark pins

| Source | Revision | Package SHA-256 | Benchmark input SHA-256 |
|---|---|---|---|
| Candidate dirty worktree | `7a36be3b8b69531dccd9215515ac793369da0a44` | `cbe75a7e54743b49de7ffee932aaeeff0b939613014dbffdf57f64245fb682b6` | `14d8f89f98588fecc426cad129c70c979c473f9b69b065d2bb18a6b4c7c3c11c` |
| Baseline archive `HEAD:src` | `7a36be3b8b69531dccd9215515ac793369da0a44` | `06d72abb444acd036fb9fa42166d8a3bf07bfa0fbaca1f0cac57fb8e5d8f0d8c` | `aa604d041afb344ceda0ab55d6b927d2f4dc54e3aae0ff0ec082d6364873be80` |

These pins are recorded in `artifacts/t10-source-pin-audit-20261001.md`. Latest candidate-scoped patch fingerprint is `9cc116c4a761374b98cae61577d3b41b6f9c8d194b4acd1b509ef1d445edc3fc` (357864 bytes). Run candidate then baseline sequentially, with competing CPU-heavy work stopped. Reject either output if revision, package, input, workload, or coverage differs from pins.

## Candidate command

Run from the candidate worktree after T20 assigns the CPU slot:

```powershell
$env:PYTHONPATH='src'
'T10_BENCH_SOURCE_ROOT','T10_BENCH_SOURCE_REVISION','T10_BENCH_SOURCE_FINGERPRINT' | ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
python -B tools/benchmark_t10_repository.py --files 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 30 --graph-repeats 30 --lookup-repeats 30 --concurrency-levels 1 --concurrency-repeats 100 --max-files 100000 --output artifacts/t10-pair-candidate-100k-20261001.json
if ($LASTEXITCODE -ne 0) { throw "Candidate benchmark failed: $LASTEXITCODE" }
```

## Baseline command

Run after candidate completes, from the same worktree. Archive committed `HEAD:src`; import that extracted package through the same harness:

```powershell
$baselineRoot = Join-Path $env:TEMP ("t10-baseline-src-" + [guid]::NewGuid().ToString("N"))
$archivePath = "$baselineRoot.tar"
New-Item -ItemType Directory -Path $baselineRoot | Out-Null
git archive --format=tar -o $archivePath HEAD src
if ($LASTEXITCODE -ne 0) { throw "git archive failed: $LASTEXITCODE" }
tar -xf $archivePath -C $baselineRoot
if ($LASTEXITCODE -ne 0) { throw "baseline extraction failed: $LASTEXITCODE" }
$env:T10_BENCH_SOURCE_ROOT = Join-Path $baselineRoot 'src'
$env:T10_BENCH_SOURCE_REVISION = '7a36be3b8b69531dccd9215515ac793369da0a44'
Remove-Item Env:T10_BENCH_SOURCE_FINGERPRINT -ErrorAction SilentlyContinue
python -B tools/benchmark_t10_repository.py --files 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 30 --graph-repeats 30 --lookup-repeats 30 --concurrency-levels 1 --concurrency-repeats 100 --max-files 100000 --output artifacts/t10-pair-head-baseline-100k-20261001.json
if ($LASTEXITCODE -ne 0) { throw "Baseline benchmark failed: $LASTEXITCODE" }
```

Baseline package-tree pin belongs in wrapper receipt `package_source_tree_sha256`; do not set `T10_BENCH_SOURCE_FINGERPRINT` for archive baseline. Baseline input pin must equal `aa604d041afb344ceda0ab55d6b927d2f4dc54e3aae0ff0ec082d6364873be80`.

## Acceptance evidence

- Both outputs must exist, match pins and identical workload settings; retain their SHA-256 and complete metric samples.
- Require candidate 100,000/100,000 indexed files, 100,000 complete caller edges, and requested-max impact coverage 99,999/99,999 at effective limit 100,000, no truncation. Baseline HEAD has legacy hard cap 100; record 100/99,999 impact coverage as incomplete/truncated. Compare `path_hint_ranking` latency/quality and impact latency at shared limit 100; no full-impact speedup claim against capped baseline.
- Keep capped and full-coverage Python fallback metrics separate from each other and from accelerator timeout/cooldown metrics. Measure process memory outside timed loops. Mark one-sample cold p95 non-meaningful.
- Compare 30 raw `lookups.path_hint_ranking.latency` samples per arm; record p50/p95 delta plus exact top-k precision, recall, and NDCG for the fixed relevant fixture path.
- Validate the paired wrapper receipt against `artifacts/t10-paired-100k-receipt-schema-20260930.json`. Do not treat local pair as T02/T20 release acceptance.
- Fresh output paths are `artifacts/t10-pair-candidate-100k-20261001.json` and `artifacts/t10-pair-head-baseline-100k-20261001.json`; both absent when this runbook was prepared.

## Root-current handoff

- Root `src/local_ai_hub/retrieval.py` has no CodeGraph/Kuzu references; root `tests/test_codegraph_package_policy.py` exists; candidate-only `tests/test_t10_retrieval_edges.py` is absent at root.
- T20 owns root integration and testing. Current bounded symbol/hash handoff is `handoff/t10-root-current-symbol-handoff-20261001.md`; Gemini seed and diagnostics remain preserved.
- Existing integrated patch status is in `handoff/t10-root-integration-audit.manifest.md`.

## Focused T10 validation receipts

TDD red command before package-tree pin fix:

```powershell
$env:PYTHONPATH='src'
$env:T10_ROOT_REPOSITORY='C:\Users\Adam\.local-ai-hub'
python -B -m pytest -q -s -p no:cacheprovider --tb=short `
  tests/test_t10_benchmark.py::test_benchmark_input_fingerprint_uses_imported_source_root
```

- Exit 1, one expected TDD red. Assertion compared `package_source_tree_sha256`: actual `2f1e797d92ca961c5eaef820f0a7185af42754dfd40b5da85a227c2b30759910`, expected `6591dd5c99616d134ea95b7ce57f6bf9a66204f8ff00f389d19d7e58586c58d6`.
- Cause: helper framed paths relative to `source_root` (`local_ai_hub/...`); receipt contract frames repository-relative paths (`src/local_ai_hub/...`). Fixed helper, added version prefix, excluded generated bytecode.

Final candidate focused command after fix:

```powershell
$env:PYTHONPATH='src'
$env:T10_ROOT_REPOSITORY='C:\Users\Adam\.local-ai-hub'
python -B -m pytest -q -s -p no:cacheprovider --tb=short `
  tests/test_t10_retrieval_edges.py::test_fused_path_ranking_is_stable_across_backend_completion_order `
  tests/test_t10_retrieval_edges.py::test_deterministic_callers_intent_combines_direct_symbols_path_hints_and_ast_edges `
  tests/test_t10_benchmark.py::test_benchmark_input_fingerprint_uses_imported_source_root `
  tests/test_t10_benchmark.py::test_external_source_root_does_not_claim_script_checkout_identity `
  tests/test_t10_benchmark.py::test_candidate_patch_fingerprint_includes_staged_changes `
  tests/test_t10_benchmark.py::test_path_hint_ranking_reports_latency_and_exact_relevance `
  tests/test_t10_benchmark.py::test_repository_benchmark_emits_symbol_search_and_concurrency_matrix `
  tests/test_t10_benchmark.py::test_benchmark_resolves_legacy_code_index_impact_cap `
  tests/test_t10_benchmark.py::test_benchmark_marks_legacy_impact_limit_as_incomplete_coverage `
  tests/test_t10_benchmark.py::test_benchmark_effective_impact_limit_matches_code_index_hard_cap `
  tests/test_adaptive_retrieval.py::test_path_hints_rank_context_evidence_without_narrowing_lexical_search
```

- Exit 0; 11 passed in 1.61s. Includes relevant retrieval ranking, deterministic tie stability, path-hint latency metric, current/baseline source identity, and legacy impact-cap handling.
- This receipt predates the later user-directed project-config consumer work below.

## Project-config consumer regression receipt

```powershell
$env:PYTHONPATH='src'
$env:T10_ROOT_REPOSITORY='C:\Users\Adam\.local-ai-hub'
python -B -m pytest -q -s -p no:cacheprovider --tb=short `
  tests/test_t10_project_config_consumers.py `
  tests/test_t10_benchmark.py::test_candidate_patch_fingerprint_includes_staged_changes `
  tests/test_preprocessor_and_deterministic.py::test_code_index_phase_removes_deleted_files_instead_of_spinning `
  tests/test_preprocessor_and_deterministic.py::test_code_index_phase_skips_ignored_refs_left_by_previous_inventory `
  tests/test_t10_acceptance.py::test_preprocessor_queues_unchanged_files_after_analyzer_version_change `
  tests/test_t10_retrieval_edges.py::test_treesitter_extracts_direct_call_edges `
  tests/test_performance.py::test_python_search_fallback_metric_is_separate_from_ripgrep_timeout `
  tests/test_performance.py::test_ripgrep_timeout_cools_down_repo_and_keeps_search_bounded
```

- Exit 0; **20 passed, 2 skipped in 12.53s**. Skips: Java/C++ Tree-sitter grammars unavailable.
- Tests cover preprocess path filtering/custom text extensions, config-digest and path-hint revision invalidation, configured project metadata, cache seeding, call-graph phase policy, language override reindex, phase skip/resume, diagnostics baseline preservation, ranked excluded hints rejected by root `repo_search`, fingerprint coverage for the new test file, and separate Python-fallback/ripgrep-timeout metrics.
- T10 candidate checkout has no `project_config.py`; standard consumer tests inject its API shape. The isolated overlay tested inheritance against the live root resolver. T20 still owns merging candidate work into root. No root writes or 100k benchmark.
