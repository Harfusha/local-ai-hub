# T02 original flaky selector RCA — 2026-10-01, v2

## RCA status

Queue-cancel flake cause is confirmed and reproducibly fixed in the candidate/root-current dirty source: `tick()` could dispatch delayed queued work before `submit()` registered its timer. The exact regression selector is RED with baseline `async_jobs.py`, GREEN with the existing `dispatch_not_before` fix. This closes RCA for the intermittent `running` versus `cancelled` assertion.

The historical unclosed SQLite `ResourceWarning` remains a separate unproven symptom. It appeared alongside a stranded worker and scratch-cleanup failure, but receipt truncation removes connection-allocation frames. Do not claim its precise connection owner or that warning leak is fixed.

## Historical failure

- Receipt: `C:\Users\Adam\AppData\Local\Temp\codex-t02-flake-20260930T201729-b78b0be9.json`; SHA-256 `f602295b4b953034f4dadace78af297e448fd4aa8da28343bcb7c091b4d07fe2`; recorded candidate HEAD `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`; requested 25 attempts, only 3 recorded.
- Attempts 2 and 3 failed `test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race`: expected `cancelled`, observed `running`. Attempt 1 captured same assertion, live `async-job-fe63de95` after manager shutdown, pending scratch cleanup, and unclosed database warnings.
- Attempt 1 failure excerpt was capped at 16,000 characters, so allocation trace for warned SQLite connections is unavailable.

## Reproducible mechanism and RED/GREEN

Regression test deterministically injects `manager.tick()` after queued-row commit in `submit()` but before delayed timer registration. Baseline HEAD implementation stores no due-time column; its `tick()` dispatches all eligible queued rows. The injected tick starts worker before delayed cancellation, so `cancel()` reports `running`.

- RED command: `C:\Python313\python.exe -X tracemalloc=5 -W error::ResourceWarning -m pytest -vv --tb=short -p no:cacheprovider tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race`
- RED ran in isolated overlay with baseline `git show HEAD:src/local_ai_hub/async_jobs.py`; exit 1 in 5.106 s. Exact assertion: `assert 'running' == 'cancelled'`. stdout SHA-256: `{q["red"]["stdout_sha256"]}`.

- GREEN command: `C:\Python313\python.exe -X tracemalloc=5 -W error::ResourceWarning -m pytest -vv --tb=short -p no:cacheprovider tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race`
- GREEN used unchanged regression selector and current candidate implementation; exit 0 in 2.392 s. stdout SHA-256: `{q["green"]["stdout_sha256"]}`. Test expectations unchanged.
- Fix stores `dispatch_not_before` in SQLite row before event/timer setup; `_dispatch()` rechecks deadline during claim; `tick()` selects only due rows. Existing-schema migration preserves old rows with default due time.

## Root-current confirmation

- Protected root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; unchanged after run. Candidate HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Overlay preserved complete tracked dirty diff SHA-256 `60438769fd9728cdff310770245b927ed2c66acd110f5f2dccda4893f2268e33` and 150 non-ignored untracked source/test/tool files. Three pinned source hashes matched root. No duplicate fix applied, preserving T08/T13 hunks.
- Current-root-overlay exact queue regression selector passed once in 5.638 s.

Combined suite ran once, no 25× loop:

`C:\Python313\python.exe -m pytest -q --tb=short tests/test_benchmark_suite.py tests/test_surface_benchmarks.py`

Result: `8 failed, 82 passed in 116.62s (0:01:56)`. Queue-cancel race selector did not fail. Other failures:

- `tests/test_surface_benchmarks.py::test_graph_unpaired_fallback_does_not_claim_paired_cases`
- `tests/test_surface_benchmarks.py::test_inference_benchmark_runs_model_goldens_and_persists_metrics_only`
- `tests/test_surface_benchmarks.py::test_run_benchmark_retains_busy_scratch_without_cleanup_watcher`
- `tests/test_surface_benchmarks.py::test_run_benchmark_rejects_concurrent_invocation_before_allocating_scratch`
- `tests/test_surface_benchmarks.py::test_run_benchmark_is_isolated_and_preserves_existing_scratch_data`
- `tests/test_surface_benchmarks.py::test_component_baselines_measure_graph_rag_batch_parent_seed_and_serena`
- `tests/test_surface_benchmarks.py::test_cli_persists_and_reports_baseline_comparison`
- `tests/test_surface_benchmarks.py::test_optional_inference_uses_runtime_load_metric_without_real_model`

In the combined run, `test_run_benchmark_is_isolated_and_preserves_existing_scratch_data` failed at `hub_rag_search` with two `RuntimeError`s and empty reason text. Teardown snapshot showed shutdown manager, no live worker/handles, and no SQLite operational errors. Combined output had zero `ResourceWarning` mentions; this does not resolve the historical warning source.

## Commands and receipts

- RED/GREEN receipt and exact commands: [queue cancel race](T02-queue-cancel-race-2026-10-01-v1/receipt.json).
- Root-current overlay command, source pins, suite command/status and full logs: [root-current handoff](T02-root-current-overlay-2026-10-01-v1/handoff.md).
- Minimal baseline-comparison cancellation/SQLite cleanup evidence: [cleanup reproducer](T02-cancel-cleanup-reproducer-2026-10-01-v1/handoff.md).

No test expectation weakened. No product edit made in this turn; fix already existed in dirty candidate/root source. No further tests ran in this turn. T02 full acceptance remains open: combined suite had failures, exact historical SQLite warning allocation remains unproven, and performance matrix is incomplete.
