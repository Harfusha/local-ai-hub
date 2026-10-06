# T02 root-current dispatch fix — 2026-10-01

## Root status

Protected root HEAD remained `98a9a1a7611af574caf20a88620c4aa3eb2e918a` before/after overlay validation. Current root working tree already contains `dispatch_not_before` logic in its dirty `src/local_ai_hub/async_jobs.py` alongside T08/T13 changes. Overlay copied full tracked diff SHA-256 `60438769fd9728cdff310770245b927ed2c66acd110f5f2dccda4893f2268e33` plus `150` non-ignored untracked files in `src/local_ai_hub`, `tests`, and `tools`; source hashes matched root. Schema migration, submit-time deadline, `_dispatch()` deadline check, and `tick()` due-row filter all present. No new patch applied: duplicate edit would collide with existing T08/T13 hunks. Regression test already present at `tests/test_surface_benchmarks.py:75`.

Root relevant source hashes after run match the before snapshot: `{"src/local_ai_hub/async_jobs.py": "ad6f8b6912e7cb836383811db2ad29c89da877afebc4b8b52c7fd57b8de0f904", "tests/test_surface_benchmarks.py": "f4e0d299384b3b3c9443390ec1001ed6b6f38d5606c0b45d8d774ded816dcf00", "tools/benchmark_surfaces.py": "dcaed06cf711090e692d4b44555c6e76ff37f06093275b63c121d7cce0ad3de0"}`.

## RED / GREEN

- Historical candidate RED: exact race selector against baseline HEAD async_jobs failed in 5.106s with `assert 'running' == 'cancelled'`.
- Candidate GREEN: same test against candidate async_jobs passed in 2.392s.
- Current root overlay regression selector: `tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race`; command `C:\Python313\python.exe -X tracemalloc=5 -W error::ResourceWarning -m pytest -q --tb=short -p no:cacheprovider tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race`; `passed`, `5.638s`.

Race: regression test calls `manager.tick()` from `_event` after queued-row commit and before timer registration. Baseline `tick()` ignored requested delay and dispatched early. Current root stores `dispatch_not_before` before `_event`; dispatch and tick both honor it.

## Root-current combined suite

Ran once in same isolated root-current overlay:

`C:\Python313\python.exe -m pytest -q --tb=short tests/test_benchmark_suite.py tests/test_surface_benchmarks.py`

Result: `8 failed, 82 passed in 116.62s (0:01:56)`. Failed selectors:

- `tests/test_surface_benchmarks.py::test_graph_unpaired_fallback_does_not_claim_paired_cases`
- `tests/test_surface_benchmarks.py::test_inference_benchmark_runs_model_goldens_and_persists_metrics_only`
- `tests/test_surface_benchmarks.py::test_run_benchmark_retains_busy_scratch_without_cleanup_watcher`
- `tests/test_surface_benchmarks.py::test_run_benchmark_rejects_concurrent_invocation_before_allocating_scratch`
- `tests/test_surface_benchmarks.py::test_run_benchmark_is_isolated_and_preserves_existing_scratch_data`
- `tests/test_surface_benchmarks.py::test_component_baselines_measure_graph_rag_batch_parent_seed_and_serena`
- `tests/test_surface_benchmarks.py::test_cli_persists_and_reports_baseline_comparison`
- `tests/test_surface_benchmarks.py::test_optional_inference_uses_runtime_load_metric_without_real_model`

Queue-race selector did not fail in combined run. `ResourceWarning` mentions: `0`. `test_run_benchmark_is_isolated_and_preserves_existing_scratch_data` reported `hub_rag_search` with two `RuntimeError` stage errors and no reason text; teardown diagnostic showed `shutdown=true`, no live worker/handles, and no SQLite operational errors. The exact historical unclosed-connection warning source remains unproven.

## Scope

No test expectation changed. No root write, 25x loop, or additional benchmark occurred. Combined suite not green; T02 acceptance remains open until independent failures and ResourceWarning ownership are resolved.

Receipts/logs: `receipt.json`, `combined-suite.json`, `regression.stdout.log`, `regression.stderr.log`, `combined-suite.stdout.log`, `combined-suite.stderr.log`.
