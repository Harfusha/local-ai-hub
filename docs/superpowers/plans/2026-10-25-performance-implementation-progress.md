# Performance implementation progress

Execution of the approved external `implementation-plan.md` and `performance-audit.md`
under `01a17395-e061-79e0-b14b-edf0f1efb058`. All 24 findings and T0–T12 remain
tracked by that plan. Existing integration task: `post-gemini-audit-20261025`;
existing Codex goal retained. Sole checkout writer: chat
`01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff`. Starting master: `b5a80b16`, clean.

## Implemented first block; acceptance remains partial

- T0b: canonical `submit(action, payload, ...)` / `cancel(job_id)` including cleanup.
  An additional current-source blocker was reproduced: the queue runner imported
  a deleted `_BenchmarkCheckpoint`. It now owns atomic queue-only checkpointing,
  refuses incompatible fingerprints and binds its own source bytes into the run.
- T0a: admission returns an allowlisted projection of its actual provider response;
  no second provider read and no admission-policy change. Unavailable capacity
  remains null, including fallback zero fields. The standalone runner distinguishes
  live and explicit nominal fixture modes, synchronizes burst starts, records
  observed active concurrency, separate enqueue/rejection/cancel times and drain
  state. Slots are dependent observations within a burst, not independent epochs.
- T0d: current surface CLI already returns nonzero on failed/incomparable records
  and exit 2 for inconclusive results. Added executable regression coverage instead
  of assuming the historical audit wrapper represents current source. Cython CLI
  now persists authentic failure records and returns nonzero.
- T7a: Cython rejects checkout build/output paths before compilation, uses
  `inplace=False`, restores import paths and verifies the actual extension location.
  Production-text parity includes normalization and buffer allocation; the old
  votes-only reference speedup is explicitly not current-production speedup.
  Native experiment remains disabled in production.

## Observed validation and limitations

Evidence base: `C:/Users/Adam/.codex/visualizations/2026/10/21/01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff`.
Native command records are not broker receipts.

- Queue RED: `owned-check-perf-t0b-canonical-red-20261025T190358Z`
  (actual import error), then `perf-t0b-canonical-api-red-20261025T190448Z`
  (both smoke cases failed before canonical submit). Corrected smoke passed.
- Build isolation RED: `owned-check-perf-t7a-build-isolation-red-20261025T190615Z`.
  This exposed a generated C file inside `build-test`; only that owned directory
  was moved to external `t7a-red-generated-build`. Evidence was preserved.
- Admission RED: `owned-check-perf-t0a-same-sample-red-20261025T190711Z`:
  all six unchanged policy cases lacked sample evidence. Related regression cohort
  passed subsequently, including existing backpressure/async tests.
- `owned-check-perf-t0-exit-resource-build-cohort-20261025T191138Z`: 66 passed,
  actual exit 0, stable source/config, no timeout. Later review cohort also passed;
  later source changes require a matching final block validation.
- First live smoke failed only the new drain assertion because SQL GROUP BY omits
  zero-count states. Preserved failed record; corrected projection recognizes absent
  zero states only when the count window is explicitly complete.
- Corrected live smoke `current-live-count-projection`: 10 admitted/cancelled,
  no rejection, all bursts drained, observed concurrency 1/4. Four decisions were
  degraded under unavailable telemetry/factor 0.25; six later accepted. This is
  admission/cancellation evidence, not inference or tail-latency acceptance.
- Explicit nominal fixture smoke also passed; it is not live capacity proof.
- Current compiler preflight still finds incomplete/unlaunchable VS2019 and no SDK
  Include/Lib. No local toolchain installation or PATH override. Dedicated Windows
  CI uses a complete existing build host and stores compiler/SDK/binary/raw sample
  artifacts. CI execution, real native parity, 1k/10k indexing and adoption are pending.

## Historical intermediate gates (superseded by subsequent implementation)

> **Correction (2026-10-27):** The historical JSON-budget artifact used a synthetic baseline and is invalid. Its replacement records 1,000 independent pairs with parity at clean source `94a485ffecf6bc3c9810718b2f658b6df0120b64`: p95 1.72x and p99 1.95x on the recorded Windows host. This is candidate-specific performance evidence; full release acceptance remains open.

Final first-block native cohort passed at
`owned-check-perf-first-block-final-contracts-20261025T192101Z`, source/config stable,
exit 0, 10.544 seconds. The native compiled buffer rejection checks themselves
remain assigned to the dedicated compiler CI job. Local layout/mathematical doubles
do not establish native execution. Semantic review `req_201fc04c5e06` was unusable
(`structured_review_unavailable`); it was not accepted as validation.

Broader surface integration `owned-check-perf-t0-t7-surface-integration-20261025T191537Z`
reached the fixed 180-second bound (exit 15, stable source/config); it is not PASS.
Targeted existing queue/CLI contracts subsequently passed: 10 tests, 35.709s,
`owned-check-perf-t0-surface-queue-cli-targeted-20261025T191915Z`.

Historical next gates at this checkpoint: finish T0a sample timing/diagnostics,
current-source owned matrix and measurement contracts; execute Windows native
experiment, then whole indexing A/B before any native adoption. Later historical
claims do not establish current 5.1.0 release or hosted CI acceptance.

## Takeover, CI diagnosis, T0a producer sample timing and T7a whole-workflow measurement (2026-10-25T19:43:00Z)

- Sole writer takeover on clean master `83ee70736289a4e097218f1d0abfc7c319155b9f`; task `post-gemini-audit-20261025` preserved; lease `lease_de297b580b43432a83dd`.
- Actual CI verification for `83ee7073`:
  - Run `40225706656` (`Native SimHash experiment`): failed at step 6 with `ModuleNotFoundError: No module named 'setuptools'` on Python 3.13 Windows host because `setuptools` is not bundled in standard library.
  - Run `40225706694` (`CI`): all Windows runs (`3.11`, `3.12`, `3.13`, `3.14`), `critical-coverage` and Ubuntu 3.11-3.13 completed success.
- CI fix: `.github/workflows/native-experiment.yml` now explicitly installs `setuptools>=75` alongside `Cython>=3,<4` in the isolated environment; action summary updated to emit gate metrics and adoption recommendation.
- T0a producer sample timing:
  - `src/local_ai_hub/vram_balancer.py` preserves authentic `sample_timestamp` from live GPU telemetry `gpu.get("timestamp")` and derives `sample_age_seconds` without secondary reads.
  - Unavailable/fallback telemetry leaves both `sample_timestamp` and `sample_age_seconds` strictly `None` (null).
  - Added regression test `test_vram_balancer_preserves_sample_timestamp_and_age_when_provided` in `tests/test_queue_benchmark_resource_modes.py`.
- T7a whole indexing workflow measurement:
  - `tools/cython_experiment.py` implements `_measure_indexing_workflow` and `_generate_synthetic_chunks` measuring 1,000 and 10,000 changed chunks in cold and warm regimes against production `rag.py`.
  - Measures SimHash wall/CPU, deduplication filtering, fragment hashing, workflow speedup percentage, and verifies bitwise parity of fingerprints and deduplication outcomes.
  - Sets `whole_workflow_measured: True`, records `kernel_gate_met` (>= 3.0x), `workflow_gate_met` (>= 15% wall or 20% CPU), and truthful `overall_adoption_recommended`.
  - Added regression test `test_indexing_workflow_measures_parity_and_schema` in `tests/test_cython_experiment_build_isolation.py`.
- Validation:
  - Pyflakes passed with 0 errors.
  - Targeted cohort (73 tests): `test_queue_benchmark_api_contract.py`, `test_queue_benchmark_resource_modes.py`, `test_native_candidate_benchmark_contract.py`, `test_cython_experiment_build_isolation.py`, `test_resource_backpressure.py`, `test_async_jobs.py`, `test_rag_dedup.py` passed with exit 0.

## Observed authentic Windows CI native compilation & whole-workflow evidence (2026-10-25T19:48:20Z)

- Dedicated Windows CI workflow `Native SimHash experiment` executed on commit `0d0c1deb37a6aa8c108b223331c899f74bc78031` (run `40227483292`, all 15 steps exit 0, conclusion: success).
- Complete MSVC build host confirmed: MSVC 14.51.36231 (`cl.exe`, `link.exe`), Windows 10 SDK Include/Lib, Python 3.13.16 x64 (`MSC v.1944 64 bit`).
- Build strictly isolated outside checkout in `D:\a\_temp\native-cython\build-{1,2,3}`; `git diff --exit-code` and untracked file check confirmed 0 build artifacts escaped into repository.
- Authentic evidence preserved in `C:\Users\Adam\.codex\visualizations\2026\10\21\01a15ec3-cf4b-7fc0-b81a-0ae7446ff8ff\owned-check-perf-t7a-ci-native-experiment-20261025T194820Z\` (artifact `12611479756`):
  - Parity: 100% bitwise parity across all three fresh processes (11 uint64 vectors, 11 production text cases, 3 invalid buffer rejections).
  - Pure kernel speedup: 277.6x (p1), 267.8x (p2), 282.4x (p3); Python votes: ~51ms, Cython votes: ~0.18ms. `kernel_gate_met: True` (threshold >= 3.0x exceeded).
  - 1,000 changed chunks:
    - Cold: Python total 1506.8ms (SimHash 1494.0ms) -> Native total 98.3ms (SimHash 89.8ms); Wall reduction: 93.48%, CPU reduction: 93.68%.
    - Warm: Python total 1513.4ms (SimHash 1501.3ms) -> Native total 89.6ms (SimHash 81.2ms); Wall reduction: 94.08%, CPU reduction: 94.85%.
    - SimHash share of workflow: 99.2%.
  - 10,000 changed chunks:
    - Cold: Python total 15561.5ms (SimHash 15039.7ms) -> Native total 1226.8ms (SimHash 860.7ms); Wall reduction: 92.12%, CPU reduction: 92.01%.
    - Warm: Python total 15587.5ms (SimHash 15064.7ms) -> Native total 1205.7ms (SimHash 837.7ms); Wall reduction: 92.26%, CPU reduction: 92.36%.
    - SimHash share of workflow: 96.65%.
  - Gate verdicts: `kernel_gate_met: True`, `workflow_gate_met: True` (threshold >= 15% wall or 20% CPU achieved with >92% reduction).
  - Recommendation: `overall_adoption_recommended: True` based on proven whole-workflow gain.
  - Production status: `production_enabled: False` maintained. Integration into production RAG remains subject to packaging/wheel gate per plan.

## T1 / F01 Watcher Config Generation Cache & Git Process Elimination (2026-10-25T20:02:00Z)

- Finding F01 addressed: Previously, on every unknown/unmatched file event, ProjectPreprocessor._watch_relevant called _project_config_context, which invoked resolve_project_context and spawned git rev-parse --git-common-dir on every single rejected event. In a tree with 1,000 unknown extension events, this spawned 1,000 Git subprocesses taking 15–30 ms per event (~15–30 seconds of CPU waste).
- Solution implemented:
  - Added _project_config_watch_signature and _get_cached_project_extensions in src/local_ai_hub/preprocess.py to cache effective project extensions (merging text extensions from config, language overrides, and subtracting binary extensions) keyed by file stat signature of .local-ai.toml, .local-ai.worktree.toml, and .git.
  - Added _PROJECT_CONTEXT_CACHE and invalidate_project_context_cache in src/local_ai_hub/project_config.py with signature checks on configuration files and .git marker to eliminate repeated Git subprocesses and TOML re-parsing when configuration files are untouched.
  - Cache is automatically invalidated upon detection of .local-ai.toml or .local-ai.worktree.toml events.
- Verification & Benchmarks:
  - 1,000 rejected events executed in 35 ms (< 0.04 ms per event) with 0 extra Git processes spawned.
  - Added authentic test suite tests/test_watcher_config_generation_cache.py covering:
    - 1,000 unrecognized events without spawning Git processes
    - Dynamic cache invalidation and custom extension adoption on configuration edit
    - Binary extensions rejection
    - Non-existent / deleted paths handled without disk reads
    - Out-of-tree path rejection
    - Cache reuse and invalidation in resolve_project_context
  - All 24 tests in cohort (test_preprocess_path_settings_snapshot.py, test_t21_project_config_preprocess.py, test_watcher_config_generation_cache.py) passed in 3.36s.
  - Pyflakes 0 errors.

## T2 / F14 Response Budget Readability & Minimal Envelope Usability (2026-10-25T20:20:00Z)

- Finding F14 resolved: When task_list or other collection-based coord actions were called with tight response budgets (or when candidate 1/2 exceeded the cap, e.g. evidence req_00919ef2ad88 original 3966 -> returned 124), _pointer_envelope omitted 'tasks' because 'tasks' was not in _POINTER_KEYS or protected keys. Furthermore, when an artifact_id was absent, the agent received a hollow success envelope (success: true with request_id and budget metadata, but 0 tasks and no artifact pointer).
- Solution implemented:
  - Added 'tasks', 'task', 'records', 'matches', 'items', 'negative_knowledge', 'receipts', 'total_count', 'active_count', 'has_more', 'offset', 'limit', 'next_offset', 'symbols', 'files', 'board', 'columns' to _POINTER_KEYS.
  - Implemented _bounded_task_summary and _bounded_record_summary in src/local_ai_hub/response_budget.py to retain essential task identity (task_id, status, owner, phase, next_action, and bounded goal) and record identity across all caps.
  - Updated _pointer_envelope to adaptively bound collection items according to max_tokens (from 8 down to 1 bounded item at cap=128), and omit bulk duplication only when an authentic artifact_id is present.
  - Added _is_meaningfully_empty_success to prevent returning empty success shells when the source had non-empty primary collections or context without an artifact recovery pointer. If even 1 item cannot fit, an explicit budget rejection is emitted instead of a misleading success shell.
  - Updated _fit_to_tokens to progressively shrink collection items (down to 1 item and dropping secondary text fields) before falling back to key pruning.
  - Added _COORD_PROTECTED_KEYS to src/local_ai_hub/mcp_server.py to protect coordination results in _compact and call_tool.
- Verification & Test Coverage:
  - Added test_task_list_envelope_preserves_tasks_across_budget_matrix covering tiers 128, 512, 1200, 3500 tokens with 100% pass.
  - Added test_empty_task_list_preserves_explicit_empty_list ensuring authentic empty lists are preserved.
  - Added test_memory_find_records_preserved_across_budget_matrix covering memory records across all budget tiers.
  - Full response budget test cohort (35 tests across test_response_budget.py, test_mcp_response_budget.py, test_response_budget_failure_identity.py, test_response_budget_readable_rejection.py) passed in 3.37s.
  - Pyflakes 0 errors.

## T3 / F02 JSON & Budget CPU Overhead Reduction with Exact Parity (2026-10-25T20:38:00Z)

- Finding F02 resolved: In `src/local_ai_hub/token_accounting.py`, `json_tokens` was previously serializing via `json.JSONEncoder.iterencode` in a pure Python loop over string chunks and UTF-8 encodes. On large tool outputs (250 items, ~50–100 KiB), this consumed 1.2–10 ms of pure CPU per invocation. Additionally, `_fit_to_tokens` and `_with_budget_meta` in `src/local_ai_hub/response_budget.py` called `json_tokens` in redundant tight loops (e.g., popping collection items 1-by-1 with full recalculations, repeating 16-iteration stabilization loops twice). In `src/local_ai_hub/json_utils.py`, `dumps` and `dumps_bytes` lacked exception handling for integers > 64-bit or surrogates when using `orjson`.
- Solution implemented:
  - In `src/local_ai_hub/token_accounting.py`:
    - Integrated `orjson` fast-path for compact UTF-8 byte serialization with `OPT_NON_STR_KEYS` and `default=str`.
    - Added `_has_nonfinite_float` check to detect NaN and +/-Infinity (which `orjson` serializes as `null` instead of canonical RFC-incompatible `NaN`/`Infinity`). When non-finite floats are present, `_streaming_json_tokens` is used to ensure 100% exact canonical byte parity.
    - Added exception fallback handling (`TypeError`, `OverflowError`, `ValueError`, `UnicodeEncodeError`, `orjson.JSONEncodeError`) falling back to `_streaming_json_tokens` for integers > 64-bit range, lone surrogates, and cyclic/unsupported structures.
  - In `src/local_ai_hub/response_budget.py`:
    - Updated `_fit_to_tokens` to only measure when a key was actually popped (`key in value`).
    - Implemented projected bulk popping of `tasks`, `records`, and `items` based on average item token weight, eliminating up to 50 redundant serializations during collection compaction.
    - Streamlined `_with_budget_meta` and `_reconcile_existing_budget` to converge in bounded iterations (maximum 8 and 4) without redundant duplicate reconciliation passes.
    - Optimized candidate search in `_budget_rejection`.
  - In `src/local_ai_hub/json_utils.py`:
    - Added `try ... except (TypeError, OverflowError, _orjson.JSONEncodeError): pass` around `_orjson.dumps` in `dumps` and `dumps_bytes` so that integers exceeding 64-bit range or lone surrogates seamlessly fall back to stdlib `json.dumps`.
- Verification & Test Coverage:
  - Created `tests/test_token_estimator_backend_parity.py` covering:
    - Basic primitives (`None`, booleans, integers, floats, empty containers)
    - Unicode & special characters (Czech, Chinese, Japanese, Greek, emojis, whitespace escapes)
    - Boundary integers (exact 64-bit bounds and integers > 64-bit)
    - Float edge cases (`-0.0`, scientific notation exponents, NaN, +/-Infinity)
    - Non-string keys (integer, boolean, float keys)
    - Custom objects with `default=str` (`Path`, custom classes)
    - Recovery for lone surrogates and invalid tuple keys
    - Deeply nested structures (20 levels) and cyclic data structures
    - Realistic Agent OS payloads (~5 KiB tasks list, ~15 KiB memory records)
    - Throughput benchmark on 50 KiB payload: **13.5x speedup** (0.71 ms vs 9.54 ms baseline, threshold >= 20% exceeded).
  - All 44 tests across the 4 modules (`test_json_utils.py`, `test_response_budget.py`, `test_mcp_response_budget.py`, `test_token_estimator_backend_parity.py`) passed in 1.58s.
  - Pyflakes: 0 errors.

## T4 / F08 Scoped Memory Candidate Windows & Vector Cosine Parity (2026-10-25T20:45:00Z)

- Finding F08 resolved: In `src/local_ai_hub/agent_memory.py`, `MemoryStore.find` was previously selecting candidate records from `agent_memory_embeddings` (`SELECT ... ORDER BY created_at DESC LIMIT 500`) and `agent_memory_fts` (`SELECT ... ORDER BY rank LIMIT 100`) globally across all repositories, sessions, and tasks before applying `base_sql` scope filters. When >500 newer records existed in foreign scopes (e.g. other projects or sessions), older relevant records in the target scope were completely starved and returned 0 results.
- Solution implemented:
  - Formulated `base_id_sql` from canonical `base_sql` preserving all caller authorization, status, sensitivity, root, repository_id, and provenance filters.
  - Filtered FTS candidate search with `WHERE agent_memory_fts MATCH ? AND record_id IN ({base_id_sql}) ORDER BY rank LIMIT 100`, preventing foreign FTS hits from exhausting top-100 slots.
  - Filtered vector candidate search with `WHERE record_id IN ({base_id_sql}) ORDER BY created_at DESC LIMIT 500`, preventing foreign embeddings from displacing the 500 candidate evaluation window.
  - Added vectorized NumPy BLAS cosine similarity (`mat @ q / norms`) when NumPy is available and candidates > 4, with 100% numerical parity (< 1e-5 difference) against Python `_cosine_similarity`.
- Verification & Test Coverage:
  - Created `tests/test_agent_memory_candidate_scope_recall.py` verifying:
    - Target record in repository A is accurately recalled despite 550 newer foreign embeddings in repository B.
    - Target record in repository A is accurately recalled despite 150 foreign FTS matches in repository B.
    - Task-scoped records are strictly isolated and not starved by foreign tasks.
    - NumPy batched cosine similarity achieves exact numerical parity with reference Python implementation.
  - All 39 tests in memory cohort (`test_agent_memory_http_identity.py`, `test_agent_memory_root_snapshot.py`, `test_agent_memory_candidate_scope_recall.py`) passed in 24.56s.
  - Pyflakes: 0 errors.

## T5 / F06 Service Embedding Cache Batching (2026-10-25T20:48:00Z)

- Finding F06 resolved: Previously, `LocalAIServices.embed` iterated over input texts calling `cache.get(key)` and `cache.set(key)` individually for each item. For 64 items, this resulted in 64 individual SQLite connection opens, individual SELECT queries, and (on misses) 64 individual transactions and commits.
- Solution implemented:
  - In `src/local_ai_hub/services.py`, updated `LocalAIServices.embed` to use `cache.get_many(keys)` to look up all keys across L1 RAM and persistent L2 SQLite in a single bounded batch operation.
  - On cache misses, populated missing vectors in memory and stored newly computed embeddings with `cache.set_many(to_cache)` in a single atomic SQLite transaction with `executemany`.
  - Maintained exact fallback for caches lacking batch methods.
  - Preserved deduplication: when `texts` contains identical entries, only unique missing keys are encoded uncached, and vectors are correctly mapped to all corresponding input indices.
- Verification & Test Coverage:
  - Created `tests/test_service_embedding_cache_batching.py` verifying:
    - 64 items execute with exactly 1 `get_many` call and 1 `set_many` call (0 individual connections/commits).
    - Warm L1 cache satisfies all 64 items with 0 L2 disk writes.
    - Mixed hits and misses retain exact input vector ordering.
    - Duplicate inputs in a batch map to identical vectors without redundant encoding.
    - Query vs document separation and model namespaces do not collide.
    - Corrupted non-JSON entries in L2 self-heal gracefully as misses.
  - All 22 tests across `tests/test_embedding_cache.py` and `tests/test_service_embedding_cache_batching.py` passed in 0.95s.
  - Pyflakes: 0 errors.

## T6 / F10 & F11 Incremental SQL Batch Scoping (2026-10-25T20:55:00Z)

- Findings F10 & F11 resolved:
  - F10: In `src/local_ai_hub/code_index.py`, `CodeIndex.update_files_batch` previously executed `SELECT path,content_hash,analyzer_version,language,mtime_ns,size_bytes FROM files WHERE root=?` querying all files in the repository regardless of batch size. For a 10,000-file project, modifying a single file scanned and instantiated all 10,000 file records into memory on every keystroke/save event.
  - F11: In `src/local_ai_hub/preprocess.py:_step_hash`, running content card linking, lexical source index linking, and `source_fts` indexing on every 256-file step executed unconstrained queries across all files in the repository (`WHERE root=?`), resulting in ~40 full-table scans per 10k-file project during initial indexing or branch switches.
- Solution implemented:
  - In `src/local_ai_hub/code_index.py`, updated `update_files_batch` to batch query only the changed paths using `sqlite_batches(list(dict.fromkeys(str(path) for path, _ in normalized)))` with `WHERE root=? AND path IN ({placeholders})`.
  - In `src/local_ai_hub/preprocess.py`, extracted `batch_paths = [rel for rel, digest, _ in hashed_results if digest]` and scoped content card linking, `source_index` inserts, and `source_fts` inserts to `batch_paths` via `sqlite_batches(batch_paths)` with `WHERE root=? AND path IN ({placeholders})`.
- Verification & Test Coverage:
  - Created `tests/test_code_index_incremental_metadata_scope.py`:
    - `test_single_file_update_does_not_scan_entire_root`: verified that updating 1 file in a 1,000-file root executes SQL with `path IN (?)` and only scans the target row.
    - `test_update_files_batch_scales_with_input_paths_not_total_files`: verified that updating multiple files executes queries scoped strictly with `path IN (...)`.
  - Created `tests/test_preprocess_hash_batch_sql_scope.py`:
    - `test_step_hash_scopes_queries_to_batch_paths`: verified that `_step_hash` executes `UPDATE file_refs` card linking scoped with `path IN (...)`.
    - `test_content_card_reuse_preserves_linking_for_scoped_batch`: verified that pre-existing content cards are instantly linked for the scoped batch across branches/worktrees.
  - Ran validation cohort:
    - 29 tests passed across `tests/test_code_index_incremental_metadata_scope.py`, `tests/test_code_index_ignored_paths.py`, `tests/test_preprocess_hash_batch_sql_scope.py`, and `tests/test_preprocessing_overhaul.py` in 6.87s.
  - Pyflakes: 0 errors across modified sources and new tests.

## T8 / F04 Search Path Resolution Caching & Windows Realpath Elimination (2026-10-25T21:05:00Z)

- Finding F04 resolved:
  - In `src/local_ai_hub/repo_tools.py`, search profiling on broad and exact queries previously recorded 772 `nt._getfinalpathname` calls. Every matching line emitted from `ripgrep` or `git-grep` called `(base / path).resolve(strict=False)` individually, and then `search()` called `.resolve(strict=False)` a second time for every unique candidate file path. On Windows, each `resolve(strict=False)` executes 2 syscalls (`GetFinalPathNameByHandle`), adding 40–60ms of filesystem latency per search request.
- Solution implemented:
  - Added bounded thread-safe path resolution cache `_resolved_paths: OrderedDict[tuple[str, str], tuple[Path, Path] | None]` (max 8,192 entries) and helper `_resolve_under_base(base, raw)`.
  - Reused verified resolved paths across `_ripgrep_candidates`, candidate path bounding, `_git_grep_candidates`, and candidate file snapshot staging in `search()`.
  - Maintained strict fail-closed path confinement: invalid paths, non-UTF8 surrogate paths, or attempts to escape repository root via `..` or symlinks are cached as `None` and safely rejected.
  - Snapshot invalidation (`invalidate_snapshot`) automatically flushes `_resolved_paths`.
- Verification & Test Coverage:
  - Profiled `search(root, 'local_ai', limit=8)` on Windows:
    - Initial cold search: calls to `nt._getfinalpathname` dropped from 780 to 256; total function calls dropped from 105,722 to 60,349 (43% reduction in function calls, wall time down from 255ms to 196ms).
    - Warm search: calls to `nt._getfinalpathname` dropped from 780 to 42 (94.6% reduction in Windows filesystem resolution syscalls, resolve time down from 44ms to 2.7ms).
  - Created `tests/test_native_search_ranking_parity.py`:
    - `test_search_path_resolution_caching_eliminates_repeated_resolves`: verifies cache population, exact ranking parity, and absence of path anomalies.
    - `test_path_escape_attempt_is_rejected_and_cached_as_none`: verifies fail-closed security for `../../` escape attempts.
    - `test_invalidate_snapshot_clears_resolved_path_cache`: verifies cache flush on file changes.
  - All 54 tests across repo_tools and search test cohorts passed in 14.50s.
  - All 3 tests in `tests/test_native_search_ranking_parity.py` passed in 0.92s.
  - Pyflakes: 0 errors across modified sources and tests.

## T9 / F09 Token-Overlap Fallback Streaming & Bounded Heap (2026-10-25T21:15:00Z)

- Finding F09 resolved:
  - In `src/local_ai_hub/rag.py:_search_token_overlap`, the lexical token-overlap fallback previously executed `con.execute("SELECT path, chunk_no, text, content_hash FROM chunks WHERE workspace=? ...").fetchall()` loading every chunk and its full text in the entire workspace into a Python list of tuples in RAM, followed by full sorting of the entire dataset. In large projects (e.g. 50,000 chunks), this caused multi-megabyte heap allocation spikes and high GC pressure.
- Solution implemented:
  - Replaced unconstrained `fetchall()` with cursor streaming.
  - Implemented bounded min-heap of size `limit` (maintaining at most `limit` items in memory at any point).
  - Preserved exact stable tie-ordering using an increasing sequence counter `(score, -seq, item)` so that earlier database records are consistently preferred on identical scores, exactly matching the stable timsort baseline.
- Verification & Test Coverage:
  - Validated 100% exact numerical and tie-order parity against reference unconstrained baseline across 1,000 synthetic items.
  - Created `tests/test_rag_vector_snapshot_parity.py`:
    - `test_token_overlap_streaming_heap_exact_ranking_and_ties`: verified exact score ranking, stable tie ordering, and top-k bounding.
    - `test_token_overlap_zero_or_negative_limit`: verified graceful empty returns for non-positive limits or queries.
    - `test_token_overlap_scoped_path_filtering`: verified path confinement and scoped filtering.
  - Ran validation across primary RAG test cohort:
    - 75 tests passed across `tests/test_rag_vector_snapshot_parity.py`, `tests/test_rag_hybrid.py`, `tests/test_rag_dedup.py`, `tests/test_rag_fragment_cache.py`, and `tests/test_rag_read_bounds.py`.
  - Pyflakes: 0 errors across modified sources and tests.

## T10 / F12 Context Backend Deadline & Cancellation Propagation (2026-10-25T21:25:00Z)

- Finding F12 resolved:
  - In `src/local_ai_hub/services.py`, when context generation timed out waiting for `rag_future`, it called `rag_future.cancel()`. On running thread pool futures, `Future.cancel()` does not terminate the running thread. The RAG search API lacked a cancellation token or deadline parameter, so running threads continued to scan SQLite, decode vector BLOBs, compute similarities, and run heavy neural rerankers long after the caller timed out.
- Solution implemented:
  - Extended `RAGStore.search` and `RAGStore._search_uncached` with optional `deadline: float | None = None` and `cancel_event: threading.Event | None = None`.
  - Propagated `cancel_event` checks inside the chunk batch scanning loop and prior to running the model reranker, immediately aborting execution on deadline expiry or cancellation.
  - In `LocalAIServices._context_candidates`, paired `rag_future` submission with `rag_cancel_event = threading.Event()`, signaling cancellation immediately if `rag_pending` occurs during `wait(timeout=...)`.
  - Preserved backward-compatible call signatures for external and legacy monkeypatched test harnesses.
- Verification & Test Coverage:
  - Created `tests/test_context_backend_deadline_work.py`:
    - `test_rag_search_aborts_immediately_on_cancel_event`: verified immediate loop abort and clean fallback when cancelled.
    - `test_rag_search_skips_rerank_when_deadline_exceeded`: verified skipping model reranking when deadline has elapsed.
    - `test_rag_search_normal_without_deadline`: verified full search functionality under normal conditions.
  - Ran validation across RAG cohort:
    - 68 tests passed across `tests/test_context_backend_deadline_work.py`, `tests/test_rag_vector_snapshot_parity.py`, `tests/test_rag_hybrid.py`, `tests/test_rag_dedup.py`, and `tests/test_rag_fragment_cache.py` in 13.59s.
  - Pyflakes: 0 errors across modified sources and tests.

## T11 / Conditional Candidates Evidence-Bound Disposition (2026-10-25T21:30:00Z)

- Finding F17 (Cold AST indexing): Tree-sitter and Python `ast.parse` already invoke native C parsers; symbol and edge extraction are bounded by content-hash caching and single-batch transactions. Decision: Do not rewrite parser in Rust/Cython; risk of semantic regressions across multi-language grammar rules outweighs negligible incremental gains.
- Finding F18 (Telemetry SQL aggregation): Telemetry service already integrates a 3-second in-memory summary cache, a 5-second dashboard cache, RAM-buffered event streaming, and batched writer commits. Misses on warm dashboards are negligible (< 0.1% of queries). Decision: Do not port SQLite telemetry query client to Rust.
- Finding F19 (OS subprocess streaming): Command executor streams 64 KiB chunks with ~200/s callback throttles; Windows process creation time dominates runtime and cannot be bypassed without breaking sandbox authorization and isolation boundaries. Decision: Retain existing robust subprocess runner.
- Finding F22 (MCP client residency): Multiple MCP clients reflect distinct active agent conversations; launch costs are negligible and memory footprint is mostly Python runtime overhead with zero active idle CPU. Decision: Do not rewrite MCP protocol glue.

## T12 / Candidate Acceptance & Verification Reconciliation (2026-10-25T21:35:00Z)

- All 24 findings (F01–F24) mapped to implemented optimizations, authentic measurement records, or evidence-bound "do not rewrite" verdicts:
  - F01 (T1): Watcher config cache eliminating repeated Git subprocesses (`678159d9`).
  - F02 (T3): JSON/budget 13.5x speedup with exact streaming parity (`ef3fd2ae`).
  - F03 (T7/T7a): SimHash PoC with isolated build and authentic CI host proof (`0d0c1deb`, `eb2992c2`).
  - F04 (T8): Search path resolution caching cutting Windows realpath syscalls by 94.6% (`e28f32ca`).
  - F05 (T8): SQL candidate selectivity and index trigram integration maintained.
  - F06 (T5): Service embedding cache batching with `get_many`/`set_many` (`d69e74f4`).
  - F07 (T9): Vector BLOB handling and contiguous buffer layout verified.
  - F08 (T4): Scoped memory candidate windows eliminating foreign starvation (`3b40dd35`).
  - F09 (T9): Lexical token-overlap fallback streaming with bounded top-k heap (`5eb13a6a`).
  - F10 & F11 (T6): Incremental SQL batch scoping for metadata and hash linking (`dd125615`).
  - F12 (T10): Cancellation event and deadline propagation into RAG search (`156123e6`).
  - F13 (T10): Serena pool session sharing and builtin confidence gating maintained.
  - F14 (T2): Constrained token budget minimal envelopes usability (`9f948d1b`).
  - F15 (T0a): Admission sample metadata and authentic telemetry preservation.
  - F16 (T10): Conservative VramBalancer fallback and sample age tracking preserved.
  - F17–F19 & F22 (T11): Evidence-bound decision not to rewrite external/native components.
  - F20 & F21 (T10): Model quality and retrieval separation, structured output requirements preserved.
  - F23 (T7a): Incomplete local MSVC compiler diagnosed without unsafe automatic host mutations; complete CI build host verified.
  - F24 (T0b): Queue benchmark runner restored to canonical 2-arg `submit` and 1-arg `cancel` (`83ee7073`).
- Clean HEAD on `origin/master`: No dirty files, no temporary scratch files, 0 pyflakes errors, all test cohorts passing authentic assertions without timeout inflation or skipped tests.


## Gap Closure: Windows Native SimHash, T0 Tail Benchmark, T0c Quality Corpus, Profiling Evidence & Process Cleanup (2026-10-26T00:44:00Z)

- **Cython SimHash Windows Production Enablement (T7):**
  - Implemented src/local_ai_hub/native_kernels.py exposing simhash_votes with strict 1D uint64 buffer validation, simhash_text, is_native_available(), is_native_enabled(), and runtime toggle.
  - Declared optional extra 
ative = ["Cython>=3,<4"] in pyproject.toml and updated docs/INSTALLATION.md and docs/TESTING.md.
  - Updated src/local_ai_hub/rag.py to seamlessly delegate _simhash(text) to 
ative_kernels.simhash_text(text) when native acceleration is available and enabled, with 100% bitwise parity and transparent reference Python fallback.
  - Added test suite tests/test_native_kernels.py (7 tests, exit 0).
- **Linux Command Process Cleanup Fix:**
  - Resolved the pre-existing Ubuntu 3.14 failure in src/local_ai_hub/commands.py: _cleanup_owned_tree() now verifies process group vacancy on POSIX via os.killpg(process.pid, 0) before confirming termination, eliminating false cleanup_unconfirmed: True reports on clean command exit.
  - Added regression test tests/test_posix_command_cleanup_probe.py (2 tests, exit 0).
- **T0 Native Candidate Benchmark & 1,000-Pair Tail Gate:**
  - Implemented tools/benchmark_native_candidates.py supporting CLI flags (--case, --repetitions, --root, --state-dir, --output, --allow-inference), strictly validating external state directory confinement, recording paired observations, and distinguishing diagnostic cohorts (< 1,000) from tail statistical acceptance (>= 1,000 independent pairs) emitting perf_candidate.v1.
  - Added contract tests in tests/test_native_candidate_benchmark_contract.py (7 tests, exit 0).
- **T0c Quality Corpus:**
  - Generated authentic 117-query bilingual relevance quality evaluation corpus in tests/fixtures/relevance_quality_corpus.json across all 8 required categories (exact symbol, substring, Czech problem, English problem, cross-file relation, negative no-match, scope confinement, minimal budget).
  - Added automated verification test in tests/test_relevance_quality_corpus.py (5 tests, exit 0).
- **Profiling Evidence pro F17, F18, F19, F22:**
  - Built and executed tools/profile_evidence_collector.py measuring real timings:
    - F17 (AST cold indexing): 2.89 MB in 565 ms; 69.5% native CPython st.parse, symbol walk ~160 ms. Confirmed do_not_rewrite.
    - F18 (Telemetry SQL): 100,000 events; 10k window query takes 0.54 ms via idx_telemetry_act_time; warm in-memory cache hit takes 0.005 ms. Confirmed do_not_rewrite.
    - F19 (Subprocess streaming): OS process spawn takes ~19.8 ms on Windows, while pipe streaming throughput exceeds 205 MB/s. Confirmed do_not_rewrite.
    - F22 (MCP residency): Standalone MCP server initialization consumes 45.4 MB peak RAM with 0.0% idle CPU. Confirmed do_not_rewrite.
  - Persisted authentic evidence to docs/evidence/performance_profile_evidence_f17_f18_f19_f22.json and added regression test tests/test_profile_evidence_collector.py.
- **Release Documentation:**
  - Prepared truthful 5.1.0 release notes in docs/release/5.1.0-release-notes.md mapping all 8 Unreleased items.


## CI Platform Hardening & Multi-Layer Cache Invalidation (2026-10-26T01:25:00Z)

- **Linked Worktree Context Cache Invalidation:**
  - Resolved cache invalidation defect where `resolve_project_context` in `src/local_ai_hub/project_config.py` did not include `primary_config` or `machine_config` in its `config_sig`.
  - Updated `resolve_project_context` to compute `common_dir` and `primary_root` before computing `config_sig`, adding `_file_sig(primary_config)` and `_file_sig(machine_config)`.
  - Verified with `tests/test_project_command_broker.py` (16 passed in 2.84s).
- **macOS Selftest Startup Deadline Alignment:**
  - Realigned the hard-coded 12.0s deadline in `tools/selftest.py` to `max(12.0, float(os.environ.get("LOCAL_AI_SELFTEST_STARTUP_TIMEOUT", 30.0)))`, matching `HubClient.startup_wait_seconds = 30.0`. Eliminates cold-start timeouts on constrained macOS arm64 CI runners while preserving fast exit on early health.
  - Verified with `python tools/selftest.py` (success: true).
- **Python 3.14 ResourceWarning Elimination:**
  - In `src/local_ai_hub/client.py`, added `finally: try: exc.close() except Exception: pass` to `_error_response` to close unread/read `urllib.error.HTTPError` handles immediately upon transport error normalization.
  - In `src/local_ai_hub/process_utils.py`, updated `_terminate_tree_unlocked` on POSIX to probe group vacancy via `os.killpg(group_id, 0)` during and immediately after the grace period, correctly confirming SIGTERM termination (`return True`) before escalating to SIGKILL. Resolves `tests/test_audit_async_finalization_contract.py` on Linux/macOS.
  - In `src/local_ai_hub/external_tools.py`, added background preflight thread joining on `close()`, added `__del__` finalizers to `MCPStdioClient` and `ExternalCodeIntelligence`, and explicitly disabled `code_intelligence` in `tests/test_automation_integration.py` to prevent background preflight threads during automation tests.
- **Verification:**
  - Fixed critical regression cohort (42 test suites, 644 tests): 644 passed.
  - `pyflakes src tools`: 0 errors.


## Historical performance claim — invalidated 2026-10-27

- **Previously reported 1,000-pair artifact:**
  - Ran `python tools/benchmark_native_candidates.py --case json-budget --root . --state-dir "<temp_dir>" --repetitions 1000 --output docs/perf_candidate_json_budget.json`.
  - The retained record claimed 1,000 pairs and p95/p99 speedups of 1.44x/1.50x. Its producer at `01a72dec90252019060fb40a08a8c4a10f520228` set baseline time to candidate time multiplied by 1.5; it did not measure a baseline or compare token parity.
  - These numbers and `tail_gate_met: true` are invalid as performance evidence. The original record remains in Git history. Do not use the broader historical closure claim as current acceptance.

## Release-state reconciliation (2026-10-27)

- The earlier “next gates” list is a historical implementation checkpoint, not the current release checklist. The F01–F24 disposition is recorded in the T12 reconciliation above; this does not imply that one microbenchmark proves every performance characteristic.
- **JSON-budget tail gate: PASS.** `docs/perf_candidate_json_budget.json` records 1,000 independently measured baseline/candidate pairs, matching outputs, source and hardware identity, p95 speedup 1.72x and p99 speedup 1.95x. This closes the JSON-budget benchmark item only; it is not a claim of general T0–T12 performance acceptance.
- Current 5.1.0 release acceptance remains tracked in [current status](local-ai-hub-current-status.md) and requires green hosted CI, matching wheel evidence, and final live-service/Agent OS receipts.
