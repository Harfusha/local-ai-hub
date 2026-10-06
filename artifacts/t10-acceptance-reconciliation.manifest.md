# T10 acceptance reconciliation

As of 2026-09-30. Audit uses existing T10 checkout only; no root/master writes or new checkout.

## Candidate and ownership

- Checkout: `C:\Users\Adam\.codex\worktrees\t10-resume-20260926\.local-ai-hub`
- Candidate HEAD: `7a36be3b8b69531dccd9215515ac793369da0a44`
- Manifest saved at `C:/Users/Adam/.codex/worktrees/t10-resume-20260926/.local-ai-hub/artifacts/t10-acceptance-reconciliation.manifest.md`.
- Actual source checkout: root `C:/Users/Adam/.codex/worktrees/t10-resume-20260926/.local-ai-hub`; branch `codex/t10-resume-20260926`; `git rev-parse HEAD` = `7a36be3b8b69531dccd9215515ac793369da0a44`. Working tree is dirty, no staged paths. Tracked dirty: `README.md`, `src/local_ai_hub/async_jobs.py`, `code_index.py`, `deterministic.py`, `preprocess.py`, `repo_tools.py`, `services.py`, `treesitter_parser.py`, `tests/test_adaptive_retrieval.py`, `test_affected_tests.py`, `test_async_jobs.py`, `test_codegraph_package_policy.py`, `test_performance.py`, `test_surface_benchmarks.py`, `test_t10_acceptance.py`, `test_t10_retrieval_edges.py`, `tools/benchmark_surfaces.py`. Untracked: `artifacts/`, `tests/test_affected_tests_no_code_index.py`, `test_preprocess_operational_mode.py`, `test_t10_benchmark.py`, `test_t10_snapshot_cache_capacity.py`, `test_t10_transitive_dependencies.py`, `tools/benchmark_t10_repository.py`.
- T10 hunk/file identity map (Git blob IDs are whole-file IDs; mixed files include inherited hunks, preserved as-is):
  - `src/local_ai_hub/code_index.py` — `CodeIndex.impact`: transitive import traversal; dependent ceiling 10,000 → 100,000. HEAD blob `8e3cff316e9a257b6246229d501fba954edfe527`; worktree blob `0b228ea4024ee64c63339f8ad298f7ebc1dd35df`.
  - `src/local_ai_hub/deterministic.py` — `DeterministicEngine.affected_tests`: lazy CodeIndex fallback. HEAD `ba36b2d9d9b3e4a061f392425f80ad553b716331`; worktree `e777904aad681b5d7f79143c12543707508032a9`.
  - `src/local_ai_hub/preprocess.py` — `ProjectPreprocessor`: operational pause/resume. HEAD `6f3efedb919105b1eda049e505404d06ccd490ea`; worktree `8532a6059ad0da70e92f8d9507220ce78fdf9cd6`.
  - `src/local_ai_hub/repo_tools.py` — `RepositoryTools`: bounded Python fallback metric and generated metadata exclusion. HEAD `35b6ec45b40abeb6c18c32368454727d537b9923`; worktree `bba1175e99630554614bd49c01c71417202c1fe4`.
  - `tests/test_t10_acceptance.py` — mixed inherited file; T10 >10k-impact regression. HEAD `fcbe2e46978210e70afd2f3a66b04cb41e5320e6`; worktree `8f6bd40d80249d1e01ebb2a1b989555c257eb9d1`.
  - T10-only added paths absent at HEAD: `tests/test_affected_tests_no_code_index.py` worktree `6f34ae94618daff99adbdd01231600486c21a2d4`; `tests/test_preprocess_operational_mode.py` `144edb23bdedfae315f6313a863f7172ce71f3b0`; `tests/test_t10_benchmark.py` `c9efb017cb6e3a6dd0d245644e32e9398abfde73`; `tests/test_t10_snapshot_cache_capacity.py` `a27f8fb7cdc47fcf55db1c40ec7d534259db21c1`; `tests/test_t10_transitive_dependencies.py` `5a0bf0bc1616c28d2acafa9b2a977d258f71a5a1`; `tools/benchmark_t10_repository.py` `829a3aeec71860242a3c9a72ec3293f5af2aa37f`.
- T10 worktree remains dirty and has mixed inherited files. Known T10 hunks: operational pause in `preprocess.py`; transitive import graph in `code_index.py`; bounded Python fallback metrics and metadata-directory filter in `repo_tools.py`; lazy no-CodeIndex graph in `deterministic.py`; T10 benchmarks, fixtures, and artifacts.
- Mixed current worktree source blobs: `code_index.py` `2115c372148acaf0c43f40824481f64cb2058f62cc37bd966b0555a156a528b9`; `deterministic.py` `e777904aad681b5d7f79143c12543707508032a9`; `preprocess.py` `8532a6059ad0da70e92f8d9507220ce78fdf9cd6`; `repo_tools.py` `bba1175e99630554614bd49c01c71417202c1fe4`.
- Other dirty paths remain inherited or mixed; do not export wholesale: `README.md`, `async_jobs.py`, `services.py`, `treesitter_parser.py`, `test_adaptive_retrieval.py`, `test_affected_tests.py`, `test_async_jobs.py`, `test_performance.py`, `test_surface_benchmarks.py`, `test_t10_acceptance.py`, `test_t10_retrieval_edges.py`, `benchmark_surfaces.py`.
- Known T10 test/script blobs: `test_t10_transitive_dependencies.py` `5a0bf0bc1616c28d2acafa9b2a977d258f71a5a1`; `test_affected_tests_no_code_index.py` `6f34ae94618daff99adbdd01231600486c21a2d4`; `test_preprocess_operational_mode.py` `144edb23bdedfae315f6313a863f7172ce71f3b0`; `test_t10_benchmark.py` `c9efb017cb6e3a6dd0d245644e32e9398abfde73`; `test_t10_snapshot_cache_capacity.py` `a27f8fb7cdc47fcf55db1c40ec7d534259db21c1`; `test_t10_acceptance.py` `8cacf6b1a4a3d8677cf89d35ddc17f35e2341388e7340e6a9583e73ef030a251` (mixed inherited file; T10 regression added); `benchmark_t10_repository.py` `829a3aeec71860242a3c9a72ec3293f5af2aa37f`.

## Plan acceptance

Plan source: `docs/superpowers/plans/2026-09-22-hub-quality-performance-master-plan.md`, T10 section, lines 239–250.

| Criterion | Evidence | Status |
|---|---|---|
| Adaptive retrieval ownership, backend selection by confidence/deadline | Existing 177-test receipt covers high-confidence optional-backend skip, deadline exhaustion, disabled/timeout/crash/malformed backend handling, RAG degradation, evidence coverage | Local tests pass; no live Serena benchmark |
| Scan/parse/SQL/graph profile, hash reuse, incremental invalidation | Existing final 100k artifact reports full fixture, callers 100,000/100,000 and impact 99,999/99,999 at explicit cap; cache/graph and incremental tests | Capacity PASS on prior candidate; current-source full-size profile NOT VERIFIED under T02/T20 gate |
| Backend/fallback/freshness/coverage/truncation/evidence truthful | T10 acceptance and retrieval-edge tests in 177-test receipt | Pass for tested fixtures |
| Language/framework fixtures and negative cases | T10 acceptance/retrieval-edge fixtures; fallback Java/C++ coverage | Partial: direct Java/C++ Tree-sitter checks skipped because grammars unavailable |
| Built-in/Serena on/off/crash/timeout comparison | Adaptive tests cover Serena disabled/timeout/crash/malformed | Partial: repository benchmark did not invoke Serena; optional-backend quality comparison remains open |
| Higher-or-equal retrieval quality; latency/coverage matrix | Prior final artifact: 100k/100k index coverage, 100k callers, 99,999/99,999 max-impact; current-source 100-file smoke is full and exact | Partial: no paired live quality baseline; fresh full-size latency profile gated; default lower API limit truncates |

## Validation receipts

Existing T10 suite, before the later no-CodeIndex fallback regression:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_acceptance.py tests/test_t10_retrieval_edges.py tests/test_adaptive_retrieval.py tests/test_affected_tests.py tests/test_repo_topology.py tests/test_t10_transitive_dependencies.py tests/test_t10_benchmark.py tests/test_t10_snapshot_cache_capacity.py
```

Receipt: `177 passed, 2 skipped in 15.14s`. Skips: direct Java/C++ Tree-sitter call checks.

Later focused receipts:

- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_affected_tests_no_code_index.py tests/test_t10_transitive_dependencies.py tests/test_affected_tests.py` — `7 passed in 1.57s`.
- `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_repo_tools.py::test_generated_tool_metadata_never_enters_inventory` — `1 passed in 2.00s`.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_performance.py::test_python_search_fallback_metric_is_separate_from_ripgrep_timeout` — `1 passed in 0.30s`.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_codegraph_package_policy.py` — `6 passed in 2.35s`.
- `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_cross_repo_federation.py` — `1 passed in 0.41s`.
- Latest graph-focused selectors: `tests/test_t10_acceptance.py::test_index_update_replaces_import_and_call_dependencies`; `tests/test_t10_acceptance.py::test_code_index_impact_returns_all_dependents_above_legacy_ten_thousand_cap`; `tests/test_t10_transitive_dependencies.py::test_affected_tests_include_transitive_importers`; `tests/test_t10_transitive_dependencies.py::test_impact_traverses_imports_when_changed_file_has_no_symbols`; `tests/test_t10_transitive_dependencies.py::test_truncated_import_graph_does_not_claim_exact_dependent_count`; `tests/test_affected_tests.py::test_affected_tests_includes_ast_callers_from_code_index` — `6 passed in 1.62s`.
- Separate fallback metric receipt: `test_python_search_fallback_metric_is_separate_from_ripgrep_timeout` passed alone (`1 passed in 0.30s`) and alongside the 10,001-dependent regression (`2 passed in 0.65s`).
- T21 owner-reported integration suite — `28 passed in 7.99s`; not rerun by T10. T21 reports its `search_paths` hunk preserved.

## Benchmark artifacts

100k run command:

```powershell
python -B tools/benchmark_t10_repository.py --files 100 10000 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 3 --graph-repeats 3 --lookup-repeats 3 --concurrency-levels 1 4 --concurrency-repeats 25 --max-files 100000 --output artifacts/t10-deterministic-benchmark-max100k.json
```

- 100 / 10,000 / 100,000 files indexed; coverage `1.0` at each size.
- The auto-cap artifact indexed 100/100 files, 8,000/10,000 (`0.8`), and 8,000/100,000 (`0.08`); explicit `--max-files 100000` removed that file-inventory cap for the benchmark run.
- 100k p95: cold scan `32.24 s`; warm scan `19.84 s`; parse build `75.79 s`; warm reindex `31.95 s`; graph impact `842 ms`; peak RSS `504.8 MB`.
- Prior 100k result was incomplete because `CodeIndex.impact()` clamped dependents to 10,000. The final 2026-09-30 artifact after the 100,000 cap change reports 100,000/100,000 callers and 99,999/99,999 impact at the requested maximum. Its default smaller API call still truncates. It is prior-candidate capacity evidence; current-source full-size latency profiling remains gated as documented below.
- The separate Python search fallback still uses its 8,000-file cap by default; benchmark reports that coverage independently from ripgrep timeout metrics.
- Artifact SHA-256: max100k `750F77A3B8F20A5E70AE18D9740AC1E3A647BDBD5012DF47D638FB4EB2B5AF1C`; auto-cap run `0FD785935C533558E04BFC2968228B72D183568D50069A3A660781435E9C6EDE`.

## Owner patches

- No-CodeIndex affected-test fallback: `t10-affected-tests-no-code-index.patch`, SHA-256 `2D5BAEB0F8F4C414B18AA275E5E36D46FB1AA542DEFF768CF2FAE0DEA07C80B6`; manifest SHA-256 `65AE598D1C72F1972B3203B76F9D757353D9BAA40B3629FAD6B981A21C83FC9A`.
- Generated metadata inventory ignore: `t10-codegraphcontext-default-ignore.patch`, SHA-256 `45F7CDAE2E0F712A5A27A95AB1E232E37BBCE0713223BDF701CEF4F3765E5DAF`; manifest SHA-256 `09ACF937C88543DA670CE7ACD2176691180AA4BA96F869EB7919C3DCC93D6C87`.
- Existing `t10-transitive-root-compatible.patch` is stale; do not use as current handoff.

## Fresh current-source full-coverage benchmark — PASS

User explicitly authorized one fresh bounded 100k run after verifying that no benchmark process was live. Historical artifacts remain unchanged. Exact command:

```powershell
python -B tools/benchmark_t10_repository.py --files 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 1 --graph-repeats 1 --lookup-repeats 1 --concurrency-levels 1 --concurrency-repeats 1 --max-files 100000 --output artifacts/t10-deterministic-benchmark-resumed-100k-20260930.json
```

- Exit 0; `full_fixture`, 100,000/100,000 indexed; Tree-sitter `1.18.0`.
- Callers full coverage: complete, 100,000 expected/matched/returned, no truncation. Requested-max impact: complete, 99,999 expected/matched/returned, effective limit 100,000, no truncation. Default impact limit 50 remains explicitly truncated.
- Single-sample raw latency: cold/warm scan `21,643.887/13,615.723 ms`; index parse/build `55,456.475 ms`; warm reindex `25,149.504 ms`; CodeIndex query `0.298 ms`; repository search `373.609 ms`; full-coverage search `16,810.810 ms`; callers default/max `2.095/167.714 ms`; callees `36.344 ms`; impact default/max `183.042/939.800 ms`.
- Peak working set through case `525,205,504 bytes`; increase `485,539,840 bytes`. Each timing has one sample; these are raw measurements, with no paired speedup claim.
- Artifact SHA-256 `687d72f9bf5550d4b7925562b3e3108dddfcbf10a2adbfb924c364644f9871c4`; 2,116,006 bytes. Source revision `7a36be3b8b69531dccd9215515ac793369da0a44`; candidate fingerprint `b9caabfbd28e40d0591742a624079fd09b407a1266a7b24491617fba6a4c4700`; benchmark-input hash `68d932690e3623845cc33fd51d74406c843fa6b440afe950df8338112ca1f04e`.

## Resumed T10 acceptance receipts — 2026-09-30

This section supersedes the earlier pending-benchmark note above. Earlier 100k runs remain historical evidence; the current-source smoke run is separate.

- Assigned checkout: `C:/Users/Adam/.codex/worktrees/t10-resume-20260926/.local-ai-hub`, branch `codex/t10-resume-20260926`, HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`. Inherited dirty files and benchmark artifacts were preserved.
- `DeterministicEngine.query()` previously routed `callers` intent only through direct symbol query. It now resolves the directly mentioned symbol before path-matched symbols, adds indexed caller edges and coverage metadata, and renders caller relationships. Regression verifies that a `src/web/caller.py` path hint ranks first while callers from both `src/web/caller.py` and `tests/test_target.py` remain present.
- Context path hints now rank full lexical evidence; they no longer restrict lexical search to hinted paths. Shared ignored-path policy now applies to repository inventory, accelerated search candidates, and explicit `search_paths`; tests prove `node_modules/private.py` cannot bypass configured exclusions.
- Repaired `_coverage_scope()` control flow in `tools/benchmark_t10_repository.py`. Before repair, the existing cap test failed with `None == "max_files_cap"` because its branches followed `_effective_impact_limit()`'s return.
- Final acceptance command:

  ```powershell
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_acceptance.py tests/test_t10_retrieval_edges.py tests/test_adaptive_retrieval.py tests/test_affected_tests.py tests/test_repo_topology.py tests/test_t10_transitive_dependencies.py tests/test_t10_benchmark.py tests/test_t10_snapshot_cache_capacity.py tests/test_affected_tests_no_code_index.py tests/test_preprocess_operational_mode.py tests/test_codegraph_package_policy.py tests/test_cross_repo_federation.py tests/test_performance.py tests/test_repo_tools.py
  ```

- Receipt after all T10 fixes: `216 passed, 2 skipped in 40.44s` (re-run after the fresh 100k benchmark). Skips are Java and C++ Tree-sitter grammar checks; those direct fixtures could not run because the grammars are unavailable. Covered callers/callees, import and call-graph transitivity, affected-test paths, result caps, path-hint ranking/no narrowing, ignored-path enforcement, benchmark scope, Python fallback metric separation, and RepositoryTools behavior.
- Current-source bounded benchmark:

  ```powershell
  python -B tools/benchmark_t10_repository.py --files 100 --parser-backend auto --cold-repeats 1 --warm-repeats 1 --graph-repeats 1 --lookup-repeats 1 --concurrency-levels 1 --concurrency-repeats 1 --max-files 100 --output artifacts/t10-benchmark-pathhint-safety-smoke-20260930.json
  ```

- Receipt: exit 0; `full_fixture`, 100 requested and indexed; callers 100/100 complete; impact 99/99 complete at limit 100. Candidate-source fingerprint `b9caabfbd28e40d0591742a624079fd09b407a1266a7b24491617fba6a4c4700`; benchmark-input hash `68d932690e3623845cc33fd51d74406c843fa6b440afe950df8338112ca1f04e`; artifact SHA-256 `371e7c5748aa56d13c5d0e3843d54126b0dbaa03f66fde44b9d5302df1329637`.
- Existing 100,000-file artifact `t10-deterministic-benchmark-final-20260930.json` is historical capacity evidence; its candidate fingerprint predates the resumed RepositoryTools/path-hint edits: 100,000/100,000 fixture files indexed; caller edges 100,000/100,000 complete; requested impact 99,999/99,999 complete at effective limit 100,000. Its standard lower API impact limit reports truncation.
- Fresh current-source 100,000-file benchmark is PASS with full callers and requested-max impact coverage, as detailed above. No paired speedup claim is made.
- External acceptance limits: no paired live Serena baseline or live CodeGraph comparison; Java/C++ direct Tree-sitter checks skipped for unavailable grammars. No root/master or unrelated worktree edits made.
- T02 baseline remains separate and in progress; no paired comparison was run. Its checkout `C:/Users/Adam/.codex/worktrees/4b5d/.local-ai-hub` is absent. T20 remains blocked with unavailable worktree `C:/Users/Adam/.codex/worktrees/ec50/.local-ai-hub`; the user's direct bounded-run authorization superseded that gate for this single T10 benchmark.

## Remaining blockers

- No paired live Serena quality/latency baseline; Serena was not invoked by the repository benchmark.
- No paired speedup comparison until T02 baseline is integrated; the current 100k receipt stands as raw performance evidence only.
- Java/C++ direct Tree-sitter checks remain skipped; fallback parser tests passed.
- Assigned `d4d2` path is an empty non-Git directory; current parent authorized this existing `t10-resume-20260926` checkout instead.

## Delegated T10 completion update — repeated 100k profile

The delegated acceptance request asked for a fresh repeated 100k profile with p95 and memory measured separately. One run completed successfully; the user then clarified that T02/T15 were running concurrently. Treat timings as **contaminated by concurrent CPU work**, useful only as raw diagnostic evidence, not an uncontended baseline. Do not launch another CPU-heavy benchmark until T02 has its exclusive baseline window.

Exact command:

```powershell
python -B tools/benchmark_t10_repository.py --files 100000 --parser-backend auto --cold-repeats 1 --warm-repeats 30 --graph-repeats 30 --lookup-repeats 30 --concurrency-levels 1 --concurrency-repeats 100 --max-files 100000 --output artifacts/t10-deterministic-benchmark-resumed-p95-100k-20260930.json
```

- Exit 0; requested/indexed files 100,000/100,000; caller query complete, 100,000 indexed edges, no truncation; requested-max impact complete, 99,999 returned at limit 100,000, no truncation. Default impact limit 50 truncates.
- Parser: Tree-sitter 1.18.0. Source revision `7a36be3b8b69531dccd9215515ac793369da0a44`; benchmark-input SHA-256 `68d932690e3623845cc33fd51d74406c843fa6b440afe950df8338112ca1f04e`; candidate fingerprint `b9caabfbd28e40d0591742a624079fd09b407a1266a7b24491617fba6a4c4700`.
- Latency p95 (ms): cold scan 32,650.0507 (1 sample); warm scan 17,737.1329 (30); parse/index build 50,805.5187 (1); warm reindex 28,798.4301 (30); capped Python search 329.4191 (30); full-coverage Python search 20,105.9628 (30); max callers 372.5042 (30); max impact 422.2396 (30). One-sample p95 values equal their sole measurement; no speedup claim.
- Memory reported separately from latency: process-lifetime peak working set through case 525,234,176 bytes; peak increase during case 485,003,264 bytes. No tracing was enabled during timing.
- Artifact size 2,126,404 bytes; SHA-256 `b1f7ad2ef9f90e5707c8d79e23dc357255820eb3e352dc1410cf6672de962fe8`.

Focused test command after the benchmark:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_adaptive_retrieval.py tests/test_t10_retrieval_edges.py tests/test_t10_benchmark.py
```

Receipt: **70 passed, 2 skipped in 6.69s**. Skips are direct Java/C++ Tree-sitter grammar checks; the grammars are unavailable. Coverage includes path-hint ranking without narrowing, explicit ignored-path and accelerated-candidate exclusion, direct-symbol callers edges, and separately capped Python fallback metrics with accelerator timeouts excluded. `git diff --check` exited 0; only existing LF-to-CRLF notices were printed. Inherited dirty and untracked worktree contents remain preserved.

Master-plan acceptance remains open on specific external/comparison criteria: no uncontended T02-paired latency/quality baseline yet; no live Serena comparison was run; CodeGraph runtime was removed, preventing live comparison; Java/C++ parser-native fixtures skipped due missing grammars. Independent T10 fixes, focused tests, coverage checks, and handoff receipts are complete. Do not mark the formal T10 goal complete until remaining acceptance is resolved or explicitly dispositioned by its owner.

### Supplemental explicit-hint exclusion coverage

Added focused tests proving `search_paths` rejects paths with a configured ignored extension and paths outside the configured extension allowlist, in addition to the existing ignored-directory test. Exact command:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_adaptive_retrieval.py -k 'explicit_path_hint_cannot_read_configured'
```

Receipt: **2 passed, 26 deselected in 0.34s**. The test edit is limited to `tests/test_adaptive_retrieval.py`; production policy remains centralized in `RepositoryTools._is_ignored_relative_path`.

Added a repository-boundary regression: `search_paths` must reject a `../` hint resolving outside the repository root. Exact command `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_adaptive_retrieval.py -k 'explicit_path_hint_cannot_escape_repository_root'`; receipt: **1 passed, 28 deselected in 0.27s**.

Independent read-only review of T10 retrieval contracts found no actionable issue: `RepositoryTools._is_ignored_relative_path` is shared by inventory, accelerated candidates, and explicit hints; `search_paths` resolves paths and verifies containment before reading; caller queries use indexed `calls` edges and preserve coverage/truncation metadata. Review is limited to these owned contracts and related tests, not the full inherited dirty diff; reviewer ran no tests.

## Authorized interim T10 profile — 10k

T02 confirmed its benchmark slot was released and permitted one bounded T10 profile while explicitly excluding the 100k graph benchmark. No matching benchmark process was live before or after this run. This 10k result is interim evidence, not a substitute for the still-pending 100k callers/impact profile.

```powershell
python -B tools/benchmark_t10_repository.py --files 10000 --parser-backend auto --cold-repeats 1 --warm-repeats 5 --graph-repeats 5 --lookup-repeats 5 --concurrency-levels 1 --concurrency-repeats 10 --max-files 10000 --output artifacts/t10-retrieval-callers-impact-profile-10k-20260930.json
```

- Exit 0; 10,000/10,000 files indexed; 10,000 caller edges; callers complete without truncation; requested-max impact 9,999/9,999 complete.
- Five-sample p95: capped search `164.1466 ms`, max callers `19.4036 ms`, max impact `61.7527 ms`.
- Memory measured separately: process-lifetime peak working set `106,942,464 bytes`; increase `66,871,296 bytes`.
- Source revision `7a36be3b8b69531dccd9215515ac793369da0a44`; input SHA-256 `68d932690e3623845cc33fd51d74406c843fa6b440afe950df8338112ca1f04e`; candidate fingerprint `b5d58df369627b2239191dccffceea4f1a088c6b6eae892333259fe7d5af7b45`.
- Artifact size `237,478` bytes; SHA-256 `58a2c7dd15cf7f7d0f5c9e1aba42488e3f0069467a904fb2fa0da611a077d6ac`.

## T10 language and removal-policy update — 2026-09-30

- Added Tree-sitter caller symbols for named TypeScript/TSX arrow functions. Added AST fixtures for both languages and a TSX phantom-call fixture. Added a C++ generic-fallback fixture for comment/string false calls.
- TDD red: before the parser change, the two named-arrow cases failed while 22 selected language cases passed; Java/C++ direct Tree-Sitter cases skipped because their grammars are unavailable. Green targeted acceptance command:

  ```powershell
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_treesitter_extracts_direct_call_edges tests/test_t10_acceptance.py::test_framework_fixtures_keep_only_real_call_edges tests/test_t10_acceptance.py::test_fallback_parsers_mask_comments_and_literals_before_building_call_edges
  ```

- Targeted receipt: `24 passed, 2 skipped in 0.82s`.
- Broader T10 acceptance command:

  ```powershell
  python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_acceptance.py tests/test_t10_retrieval_edges.py tests/test_t10_transitive_dependencies.py tests/test_t10_snapshot_cache_capacity.py tests/test_t10_benchmark.py tests/test_codegraph_package_policy.py tests/test_performance.py::test_python_search_fallback_metric_is_separate_from_ripgrep_timeout tests/test_affected_tests.py::test_affected_tests_includes_ast_callers_from_code_index
  ```

- Receipt: `165 passed, 2 skipped in 14.63s`. Skips remain Java/C++ Tree-Sitter grammar checks; generic fallback checks pass.
- Removed stale Hub-integration claims from feature, contributor, feature-audit, orchestration-skill, third-party, and historical plan docs. `docs/INSTALLATION.md` now presents CodeGraphContext only as an optional standalone external tool and states Hub does not install, invoke, configure, or depend on it. Runtime/package policy suite passed in the broader T10 run. Scanner/selftest still exclude the external `.codegraphcontext` data directory; uninstall still removes the retired `codegraph-local` registration.
- Current benchmark-input SHA-256: `527704dad336763c5858525da5a56e4efb9750107d0161da4815df046ca87e05`. Current candidate fingerprint: `144f2fe28a17ce772ed92d671585e763566e8518ef44c85fd2fb1b8aad3dba3b`; patch bytes `285336`. Current file SHA-256: `treesitter_parser.py` `5099a2defa66feb05156ff7f38f472178b288aa915847a68064eb91162018fb7`; `benchmark_t10_repository.py` `1c90d69b02d0fbc05af68c4620f139cb0348999c56b14d068a1795d60548723f`.
- Existing 10k artifact SHA-256 `58a2c7dd15cf7f7d0f5c9e1aba42488e3f0069467a904fb2fa0da611a077d6ac` and contaminated repeated-100k artifact SHA-256 `b1f7ad2ef9f90e5707c8d79e23dc357255820eb3e352dc1410cf6672de962fe8` retain their original input hash `68d932690e3623845cc33fd51d74406c843fa6b440afe950df8338112ca1f04e`; both predate these parser/benchmark edits. They are historical raw evidence, not current-source receipts.
- No new benchmark run: T02 has not completed its exclusive baseline window. Current-source full-size p95 and paired quality/speedup remain unverified; do not infer them from prior artifacts.
- Goal tool could not create a replacement goal because the existing T10 goal is unfinished and blocked. No status change made; keep acceptance open pending T02 baseline.
- Follow-up integration regression added to `tests/test_t10_retrieval_edges.py`: index a TypeScript named-arrow caller, then assert indexed `find_callers` and `find_callees` edges. Not included in the `165 passed` receipt; validation waits for an assigned test slot.
- Pending focused command after slot allocation: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t10_retrieval_edges.py::test_code_index_finds_typescript_arrow_callers tests/test_t10_retrieval_edges.py::test_call_edge_analyzer_version_rejects_stale_parse_blobs`.
- Latest candidate fingerprint after this regression: `7e4d7f86e185a32a6bde45204745c261d819a950b30a782473f8751ac523199c`; patch bytes `286313`. Benchmark-input SHA-256 remains `527704dad336763c5858525da5a56e4efb9750107d0161da4815df046ca87e05` because benchmark inputs exclude tests.
- Slot coordination: T02 says tests/benchmarks are not running; its slot queue is T03, then T04, then T02. T02 still lacks a test slot. T10 focused tests and current-source 100k profile remain queued pending explicit slot assignment.
- Static cache review found that arrow caller extraction changes cached parse output. Bumped `_PARSER_ANALYZER_VERSION` to `call-edges-v12-named-arrow-callers` and updated its freshness assertion so old parse blobs cannot hide the new edges. This change awaits the same test slot.
- Latest input hash after cache-version change: `5da2cd80e75cf938fc30241178be519590ca302ee70277d53e12e27978a1dc0c`; current candidate fingerprint `bdb93a721d011e8a27d340fb05c284e82bfdb6ba91209ca1f51abe1d3db53239`; patch bytes `286987` after adding an unrun accelerated-containment regression. Current `code_index.py` Git blob `288439d862bf2b1d402c45011873792bf503e093`; `treesitter_parser.py` blob `6a3744a6bab0891d18387c8064f3422524bca6a9`; `test_t10_retrieval_edges.py` blob `0c1cb5f2d5858c44dac48e4462e7fee26fad7bdb`.
- Independent read-only review of arrow scoping and cache invalidation found no issue. Reviewer confirmed named arrow edges are scoped to the declared symbol and the analyzer bump prevents stale parse results; no tests were run.

### User-approved search metric split

- The user approved keeping the capped Python fallback measurement separate from the ripgrep/Git accelerator probe.
- Static inspection confirms distinct `repository_search` / `repository_search_full_coverage` latency results from `repository_search_accelerator_probe` timeout, cooldown, and latency fields in `tools/benchmark_t10_repository.py`; `tests/test_t10_benchmark.py` asserts the fallback modes and accelerator probe independently. This is a source review only; no test was run for this confirmation.
- Slot status checked against live T20 on 2026-09-30: release OPEN; T10 ran its one assigned selector and released to T04. Latest queue has T05 on exclusive CPU slot and T08 next; T20 summary reports T04 39/39, without an exact receipt in this T10 worktree. No T10 parser/cache test or current-source benchmark allocation.
- Static checks: `git diff --check` exited 0; Python AST parsing passed for `preprocess.py`, `test_runtime_hardening.py`, `repo_tools.py`, and `test_adaptive_retrieval.py`; all seven prepared selector names exist. The registry selector passed once; remaining suites were not executed. Working tree remains dirty and unstaged; no inherited changes were staged or overwritten.
- Revision-pinned matrix and current-vs-HEAD 100k runbook: `artifacts/t10-revision-pinned-acceptance-matrix-20260930.md`; SHA-256 `c6a61e3a8938096e93a293a1071dad4feb79eadc8182e362dda571b85885c646`.
- Paired 100k receipt JSON Schema: `artifacts/t10-paired-100k-receipt-schema-20260930.json`; SHA-256 `d15f714943ba09ff2cc6394408d01496ee1171454eb190fb549615b4012bf97f`; JSON Schema 2020-12 meta-validation passed, no benchmark receipt was validated.
- Prepared pair pins: candidate worktree patch `bdb93a721d011e8a27d340fb05c284e82bfdb6ba91209ca1f51abe1d3db53239`, package source SHA-256 `60cc405ed644b079cca286df373cb17670f1a8ecb03aab5b0d43985e3113c277`, benchmark inputs `5da2cd80e75cf938fc30241178be519590ca302ee70277d53e12e27978a1dc0c`; HEAD baseline revision `7a36be3b8b69531dccd9215515ac793369da0a44`, package source SHA-256 `06d72abb444acd036fb9fa42166d8a3bf07bfa0fbaca1f0cac57fb8e5d8f0d8c`, benchmark inputs `35fcba4f5348ec4a90780c7ef6cf495c99ba1517a97ef6dee0d7d13959610cc1`.
- Formal goal inspection found the matching T10 goal still `blocked`; no duplicate goal created. The goal API does not support reactivation. Acceptance remains open.
- Independent read-only review confirmed the v12 cache selectors and all historical matrix p50/p95/sample/coverage values. The 100k contamination label comes from the external T02/T15 run context, not the artifact JSON. No tests or benchmarks ran during these reviews.
- T20-assigned repair of `tests/test_runtime_hardening.py`: create both temporary project roots in `test_registry_repair_reactivates_the_selected_project`, preserving its slot-rebalancing assertions. File SHA-256 `58a1ba614f6149e38ad54e9ce8480cc2dc5af6acc2898d1e8615f9b3efae1531`; HEAD `7a36be3b8b69531dccd9215515ac793369da0a44`, worktree blob `2d81cf957a559f82910d7df7defb1291f6bd945d`. Exact command passed once: exit 0, 1 passed in 0.39s. Log `artifacts/t10-registry-repair-selector-20260930.log`, SHA-256 `7148718990d7ea797310a566f73839afc086a66a233d8b87a51420dbd3998814`; slot explicitly released to T04.
- Runbook/schema review found and corrected baseline fingerprint-field misuse, missing exact coverage constraints, and underconstrained sample counts. Baseline command now leaves the harness patch field null and pins its package source SHA in the wrapper; schema pins both arms, exact coverage, and required sample counts.
- T10 plan review: required acceptance is repository retrieval (scan/parse/SQL/graph, quality/coverage and latency), not speech inference. Existing transcription contracts use placeholder byte strings and mocked CLI; quality JSONL is synthetic. No real audio fixture/model weights appeared under repository test fixtures; speech WER/real-model acceptance remains blocked. No download or user-local config inspection.
- Current-source paired 100k candidate/baseline remains unrun: T20 currently sequences T05 then T08; no uncontended T10 benchmark window is allocated. No current-source speedup claim.
- Static AST selector inventory passed for the pending TypeScript-arrow, parser-version invalidation, and unchanged-content reindex selectors; names exist in `test_t10_retrieval_edges.py` and `test_t10_acceptance.py`. No test execution.
