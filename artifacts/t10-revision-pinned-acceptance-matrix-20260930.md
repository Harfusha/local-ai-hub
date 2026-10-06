# T10 revision-pinned acceptance matrix

Updated 2026-10-01. This is an acceptance plan and evidence ledger for the current T10 worktree candidate. The paired benchmark remains unrun.

## Candidate identity

| Pin | Value |
|---|---|
| Checkout / branch | `C:/Users/Adam/.codex/worktrees/t10-resume-20260926/.local-ai-hub` / `codex/t10-resume-20260926` |
| Git base revision | `7a36be3b8b69531dccd9215515ac793369da0a44` |
| Current benchmark-input SHA-256 | `14d8f89f98588fecc426cad129c70c979c473f9b69b065d2bb18a6b4c7c3c11c` |
| Current candidate-scoped patch SHA-256 | `9cc116c4a761374b98cae61577d3b41b6f9c8d194b4acd1b509ef1d445edc3fc` (`357864` bytes) |
| Current package source tree SHA-256 | `cbe75a7e54743b49de7ffee932aaeeff0b939613014dbffdf57f64245fb682b6` |
| Parser analyzer version | `call-edges-v12-named-arrow-callers` |
| Paired baseline source | `HEAD:src/local_ai_hub` at `7a36be3b8b69531dccd9215515ac793369da0a44`; package source tree SHA-256 `06d72abb444acd036fb9fa42166d8a3bf07bfa0fbaca1f0cac57fb8e5d8f0d8c`; benchmark input SHA-256 `aa604d041afb344ceda0ab55d6b927d2f4dc54e3aae0ff0ec082d6364873be80` |
| Current gate | Prior focused aggregate: 73 unique passed, 2 skipped. Latest consumer overlay: 5 passed; supported AST calls: 9 passed. No current-source 100k profile ran; root integration remains with T20. |

The Git revision alone does not identify the dirty candidate. Acceptance results must record both the revision and current worktree fingerprint/input hash. The matrix below marks older receipts as historical where their fingerprints differ.

The paired baseline is the committed `HEAD:src/local_ai_hub` source tree, imported by the same current T10 harness used for the candidate run. Source tree SHA-256 uses `SHA256(b"T10-PACKAGE-SOURCE-TREE-V1\0" + concat(sorted(relative_path_utf8 + b"\0" + file_bytes + b"\0")))` over `src/local_ai_hub`; baseline reads blobs from `HEAD`, candidate reads current worktree files. Candidate also retains the harness's candidate-scoped patch fingerprint. This local pair is prepared as a same-host diagnostic comparator. It does not supply a T02/T20 release receipt or authorize a speedup claim.

Both arms generate the same deterministic corpus: `src/module_{number:06d}.py` for numbers `0..99999`, each with `caller_{number:06d}()` calling `shared_target()`; module zero also defines `shared_target()`. The framed fixture content SHA-256 (`T10-SYNTHETIC-CALL-GRAPH-V1\\0` prefix, followed by sorted relative path/content pairs separated by NUL bytes) is `d20f903a0bb5a2a17c605d2804a4f53a4e20f6914e8d2eda205cf05b63a8379d`.

## Correctness, cache, and limits

| Area | Required assertion | Owning selector(s) | Current evidence |
|---|---|---|---|
| TypeScript/TSX named arrows | AST emits named caller symbols and `caller -> target` call edges; indexed APIs expose both callers and callees. | `tests/test_t10_retrieval_edges.py::test_treesitter_extracts_direct_call_edges`; `tests/test_t10_retrieval_edges.py::test_code_index_finds_typescript_arrow_callers` | Direct TS/TSX Tree-sitter cases passed in the earlier `24 passed, 2 skipped` run. The new CodeIndex integration selector is **not run**. |
| Parser cache invalidation | Analyzer-version change rejects old parse blobs and reindexes unchanged source; v12 prevents old cached results hiding arrow edges. | `tests/test_t10_retrieval_edges.py::test_call_edge_analyzer_version_rejects_stale_parse_blobs`; `tests/test_t10_acceptance.py::test_code_index_reindexes_unchanged_content_after_analyzer_version_change` | Static code/reviewer check found the v12 bump wired to cache freshness. The v12-specific selector is **not run**. |
| AST/fallback decoys | TSX phantom calls and C++ fallback comments/string contents do not create false call edges; real framework calls remain. | `tests/test_t10_acceptance.py::test_framework_fixtures_keep_only_real_call_edges`; `tests/test_t10_acceptance.py::test_fallback_parsers_mask_comments_and_literals_before_building_call_edges` | Older targeted receipt: `24 passed, 2 skipped`; Java/C++ Tree-sitter grammars unavailable. It predates the current v12 fingerprint. |
| Caller/callee retrieval | Direct symbol resolution and indexed call edges both contribute; file hints affect ranking without dropping relevant callers elsewhere. | `tests/test_t10_retrieval_edges.py::test_deterministic_callers_intent_combines_direct_symbols_path_hints_and_ast_edges`; `tests/test_t10_retrieval_edges.py::test_code_index_finds_typescript_arrow_callers`; `tests/test_adaptive_retrieval.py::test_path_hints_rank_context_evidence_without_narrowing_lexical_search` | Earlier T10 receipts cover path-hint ranking and direct callers; current arrow integration still awaits slot. |
| Hint security / exclusions | Explicit paths cannot read ignored directories/extensions, disallowed extensions, or files outside the repository; accelerated candidates obey the same deny policy. | `tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_configured_ignored_directory`; `tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_configured_ignored_extension`; `tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_extension_outside_allowlist`; `tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_escape_repository_root`; `tests/test_adaptive_retrieval.py::test_ignored_directory_is_filtered_from_accelerated_search`; `tests/test_adaptive_retrieval.py::test_accelerated_search_rejects_candidates_outside_repository` | Static source review: shared `_is_ignored_relative_path` gate at `src/local_ai_hub/repo_tools.py:262`, called by inventory `:329`, accelerated results `:1098`, and explicit hints `:1782`; accelerated containment check at `:1095-1097`. Existing earlier targeted receipts passed; new containment selector awaits slot. |
| Call graph limit and truncation | Default limit is reported as truncated when insufficient; large explicit limits return full indexed caller/callee coverage and freshness metadata. | `tests/test_t10_retrieval_edges.py::test_call_graph_queries_report_truncation_and_unverified_freshness`; `tests/test_t10_retrieval_edges.py::test_call_graph_queries_honor_large_explicit_result_limits` | Prior 10k/100k artifacts show default limit 50 truncates and explicit max query completes; artifacts predate this candidate. |
| Impact coverage and cache | Requested-max impact returns all expected dependents; bounded scans report exact/inexact counts and truncation correctly; cached impact invalidates after index update. | `tests/test_t10_retrieval_edges.py::test_impact_reports_dependent_coverage_and_truncation`; `...::test_impact_result_cache_reuses_warm_result_and_invalidates_after_index_update`; `...::test_impact_reports_exact_candidate_count_when_bounded_scan_truncates`; `tests/test_t10_benchmark.py::test_benchmark_effective_impact_limit_matches_code_index_hard_cap` | Historical 10k and 100k artifacts show 9,999/9,999 and 99,999/99,999 at requested max. Current candidate profile is missing. |
| Search measurement separation | Capped Python fallback and full-coverage Python fallback have separate latency/coverage; ripgrep/Git timeout and cooldown probe is a separate result. | `tests/test_t10_benchmark.py::test_repository_benchmark_emits_symbol_search_and_concurrency_matrix`; `tests/test_performance.py::test_python_search_fallback_metric_is_separate_from_ripgrep_timeout` | Source inspection confirms separate result fields; user approved this split. Existing prior receipt passed the standalone fallback-metric test. |

Java/C++ parser-native tests remain skipped because grammars are unavailable; retain fallback-parser coverage and report the skips.

Slot-gated hint/exclusion regression command (prepared, not run):

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_configured_ignored_directory tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_configured_ignored_extension tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_read_extension_outside_allowlist tests/test_adaptive_retrieval.py::test_explicit_path_hint_cannot_escape_repository_root tests/test_adaptive_retrieval.py::test_ignored_directory_is_filtered_from_accelerated_search tests/test_adaptive_retrieval.py::test_accelerated_search_rejects_candidates_outside_repository
```

## T20-assigned registry-repair fixture

`tests/test_runtime_hardening.py::test_registry_repair_reactivates_the_selected_project` previously inserted project rows for nonexistent directories. `_repair_registry` correctly removes missing roots, which called runtime cleanup on a `__new__` fixture lacking runtime locks and aborted before commit. The fixture now creates both roots so this selector exercises slot rebalancing; its assertions remain unchanged. T20 assigned the one-test slot; T10 ran this selector once, then released the slot to T04.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_runtime_hardening.py::test_registry_repair_reactivates_the_selected_project
```

Receipt: exit 0; 1 passed in 0.39s. Log: `artifacts/t10-registry-repair-selector-20260930.log`; SHA-256 `7148718990d7ea797310a566f73839afc086a66a233d8b87a51420dbd3998814`.

## Existing p50/p95 receipts (historical only)

These figures are copied from artifacts whose input hash is `68d932690e3623845cc33fd51d74406c843fa6b440afe950df8338112ca1f04e`, not the current `5da2...` input hash. Do not use them as current-candidate acceptance or claim speedup.

| Artifact scale | Measurement | p50 ms | p95 ms | Samples | Evidence status |
|---|---:|---:|---:|---:|---|
| 10k, old candidate `b5d58df3…` | Warm scan | 1,358.7709 | 2,115.6381 | 5 | Interim exclusive slot; historical candidate |
| 10k, old candidate `b5d58df3…` | Index build | 4,359.9386 | 4,359.9386 | 1 | Single sample; p95 not meaningful |
| 10k, old candidate `b5d58df3…` | Capped Python search (1k cap) | 157.2312 | 164.1466 | 5 | Historical diagnostic |
| 10k, old candidate `b5d58df3…` | Full-coverage Python search | 1,490.3981 | 1,512.5535 | 5 | Historical diagnostic |
| 10k, old candidate `b5d58df3…` | Max callers (10k) | 15.5896 | 19.4036 | 5 | Historical diagnostic |
| 10k, old candidate `b5d58df3…` | Max impact (9,999) | 19.5479 | 61.7527 | 5 | Historical diagnostic |
| 100k, old candidate `b9caabfb…` | Warm scan | 14,583.2542 | 17,737.1329 | 30 | **Contaminated** by concurrent T02/T15 CPU work |
| 100k, old candidate `b9caabfb…` | Index build | 50,805.5187 | 50,805.5187 | 1 | Single sample; p95 not meaningful; contaminated run |
| 100k, old candidate `b9caabfb…` | Capped Python search | 275.5882 | 329.4191 | 30 | Contaminated run; accelerator timeout is separate |
| 100k, old candidate `b9caabfb…` | Full-coverage Python search | 17,094.1665 | 20,105.9628 | 30 | Contaminated run |
| 100k, old candidate `b9caabfb…` | Max callers (100k) | 250.0657 | 372.5042 | 30 | Contaminated run |
| 100k, old candidate `b9caabfb…` | Max impact (99,999) | 301.6980 | 422.2396 | 30 | Contaminated run |

The 100k accelerator probe recorded a single 15,070.6123 ms bounded failure and one ripgrep timeout. It is not part of the capped Python fallback latency distribution. Memory for the old 100k run was measured separately from timed loops; it is not a current-candidate memory receipt.

## Pending acceptance run and missing evidence

Current-candidate retrieval and project-config consumer selectors are recorded in `artifacts/t10-acceptance-current-focused-20261001.md`. The paired 100k profile requires T20 to assign an exclusive sequential window. T02 is idle and is not a blocker.

Current parser/cache selectors:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_code_index_finds_typescript_arrow_callers tests/test_t10_retrieval_edges.py::test_call_edge_analyzer_version_rejects_stale_parse_blobs
```

Then run the broader T10 correctness selectors listed above, including path-hint exclusions, cache invalidation, caller/impact limits, and benchmark output assertions. Record exact candidate fingerprint/input hash, command, exit, skips, and elapsed time.

Current-source 100k profile command (use a fresh output filename):

```powershell
python -B tools/benchmark_t10_repository.py --files 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 30 --graph-repeats 30 --lookup-repeats 30 --concurrency-levels 1 --concurrency-repeats 100 --max-files 100000 --output artifacts/t10-deterministic-benchmark-current-source-100k-20260930.json
```

Run candidate and baseline sequentially in the explicitly assigned T20 window, with competing CPU-heavy work stopped. Candidate auto-detects its current Git revision and dirty-candidate fingerprint; reject the receipt if they or the current input/tree hashes differ from the pins above. For the baseline, extract committed `src` into a unique temporary directory and direct the same harness imports there; set the source identity overrides to the baseline revision and package-tree fingerprint. The harness computes the baseline benchmark-input digest from its own script plus the imported baseline modules.

Candidate command:

```powershell
'T10_BENCH_SOURCE_ROOT','T10_BENCH_SOURCE_REVISION','T10_BENCH_SOURCE_FINGERPRINT' | ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
python -B tools/benchmark_t10_repository.py --files 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 30 --graph-repeats 30 --lookup-repeats 30 --concurrency-levels 1 --concurrency-repeats 100 --max-files 100000 --output artifacts/t10-pair-candidate-100k-20261001.json
```

Baseline command:

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
python -B tools/benchmark_t10_repository.py --files 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 30 --graph-repeats 30 --lookup-repeats 30 --concurrency-levels 1 --concurrency-repeats 100 --max-files 100000 --output artifacts/t10-pair-head-baseline-100k-20261001.json
```

Do not pass `T10_BENCH_SOURCE_FINGERPRINT` for the external baseline root: that harness field is named `candidate_scoped_patch_sha256`. It will be null for the baseline. Store the baseline package tree SHA-256 in the wrapper receipt's separate `package_source_tree_sha256` field, and require the benchmark input SHA-256 to equal the extracted-archive pin `aa604d041afb344ceda0ab55d6b927d2f4dc54e3aae0ff0ec082d6364873be80`.

The paired PowerShell benchmark commands remain prepared; no archive or current-source 100k benchmark was run. The candidate focused suite is complete for this slot; the paired wrapper receipt must validate both source pins, equal workload parameters, artifact hashes, environment, coverage, p50/p95 and separate memory. Its JSON Schema is `artifacts/t10-paired-100k-receipt-schema-20260930.json`.

Candidate acceptance must demonstrate 100,000/100,000 indexed files, 100,000 caller edges with complete untruncated max-caller coverage, and 99,999/99,999 requested-max impact coverage at effective limit 100,000. Legacy baseline impact is capped at 100/99,999 and must be recorded incomplete/truncated; compare impact latency at shared cap 100. Record p50/p95 and sample counts for scan, parse/index, warm reindex, capped and full-coverage fallback, max callers, max impact, and path-hint ranking. Keep the accelerator timeout/cooldown probe separate. Measure memory outside timed loops. The one-sample cold parse/index p95 must be labelled non-meaningful; no speedup claim without a same-workload paired baseline from T02.

Still missing for full performance acceptance:

- Current-input-hash `14d8f89f…` uncontended 100k p50/p95 plus separately measured memory and complete retrieval/impact coverage.
- Same-workload paired baseline before any speedup claim; run only in T20-assigned exclusive window.
- Java/C++ Tree-sitter grammar availability; if unavailable, keep those checks marked skipped and cite fallback coverage.
- Live Serena comparison is not part of the repository benchmark; no live Serena quality or latency result exists.

## Speech/model evidence boundary

The T10 plan acceptance is repository retrieval and does not require speech inference. Available contract coverage is synthetic only: `tests/test_transcription_contract.py` writes placeholder bytes such as `b"test audio"` and mocks the Whisper CLI; `tests/fixtures/model_quality_cases.jsonl` is evaluator data, not audio or model output. No real audio fixture or model weights appeared in the repository test-fixture inventory. Do not infer WER, transcription quality, GPU performance, or real-model acceptance from these fixtures. Speech/model E2E remains **BLOCKED** until an authorized real fixture and pinned weights are available. No download or user-local config inspection was performed.

## Independent static review

- Parser/cache review found no discrepancy: the v12 analyzer version, named-arrow scope, and focused selectors match the source and tests. Final candidate focused receipt is 73 unique passed, 2 skipped; no tests were run for this static review.
- Matrix/artifact review found no numeric discrepancy in historical p50/p95, sample counts, coverage, candidate fingerprints, or input hashes. The 100k contamination label relies on the external T02/T15 run context; the JSON artifact does not encode that fact. No tests or benchmarks were run for this review.
- Runbook/schema review caught and fixed baseline patch-field misuse, incomplete exact-coverage constraints, and underconstrained sample counts. Schema requires distinct capped/full-coverage Python fallback metrics and a separate ripgrep/Git timeout-cooldown probe; user approved this separation. Draft 2020-12 meta-validation passed; no benchmark receipt exists yet.

