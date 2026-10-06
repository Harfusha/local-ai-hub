# T02 Admission Diagnostic Protocol

Date: 2026-10-01 (Europe/Prague)

## Status and ownership

- RCA remains open. Saved run 20 failed only `hub_queue_admission` before the scratch-retention assertions at `tests/test_surface_benchmarks.py:889-908`.
- Candidate-only patch: `handoff/T02-admission-diagnostic.patch`. It changes `tools/benchmark_surfaces.py` and adds the queue failure list to the existing scratch-test assertion message. It does not change `src/local_ai_hub/async_jobs.py`, root files, acceptance thresholds, or expected outcomes.
- T08 was notified. The patch uses existing `AsyncJobManager.status()` and `stats()` APIs; no T08-owned production code changes.
- T20 owns root application and exclusive test-slot assignment. Do not run in candidate or root until T20 assigns the slot.

## Diagnostic payload

Capture only failed queue-admission samples, capped at 16 records. Each record has:

- Stable sample ID: concurrency level, repetition, and slot.
- Git source revision and generated async job ID.
- Submit and cancel booleans, state, admission state/reason, cancel-request flag, and retryable flag.
- Post-cancel status: state, attempts, cancel-request flag, and row `updated_at`.
- Shared manager state counts and cumulative counters after the probe.
- Normalized error reason/type plus diagnostic-read exception types only.

The benchmark stops the latency timer before diagnostic reads. It does not retain prompt/task payloads, raw exception text, result contents, or task IDs. Manager counters are a shared concurrent snapshot, not per-job counters. Existing benchmark fields remain unchanged; failure metadata is additive and bounded.

## Root selector receipt

T20 applied the patch to root and ran the exact selector once:

```powershell
C:\Python313\python.exe -B -m pytest -q -p no:cacheprovider --tb=short -c pyproject.toml tests/test_surface_benchmarks.py::test_run_benchmark_retains_busy_scratch_without_cleanup_watcher
```

Result: 1 passed in 15.50s. No `failed_samples` payload emitted, so this pass does not identify the historical trigger. Do not repeat the selector or combined 25-attempt run without a new bounded reproduction strategy and T20 slot assignment.

## Concrete historical queue snapshot

`handoff/T02-run20-queue-snapshot.json` extracts ordered-20 trace. At manager close, before shutdown, one queued delayed probe remained: job `fe0edd9a0e99407da72bfc2c0d68b5d0`. Eight other probe jobs had explicit `cancel` events, each `success=true/state=cancelled`. Close then moved the missing row to `cancelled`, cleared delayed IDs, and left no threads. A separate row `4b4ed40bbf5e4c228aa8ea03b0a6ca59` stayed `outcome_unknown`, consistent with fixture sentinel.

Code-order inference maps the pending row to the first level-1/iteration-0/slot-0 probe; the historical trace did not persist sample IDs. It proves missing successful probe cancellation before close, not why. Saved stdout omits per-sample `error_reasons`; cannot distinguish cancellation exception, submit/cancel response branch, or missing tracer event. The failure remains unrooted; no causal source fix is justified.

## Candidate test-order/lifecycle slice

To check for process-local leakage without replaying the 90-test suite, `tools/t02_lifecycle_pytest_plugin.py` emits bounded manager lifecycle state after each selected test. It reports only managers whose shutdown is unset or that retain live worker/dispatcher/delayed-dispatch threads; it reads no job payloads.

Candidate-only command, preserving the combined-suite file order and the relevant queue tests:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Python313\python.exe -B -m pytest -q -s --tb=short -p no:cacheprovider -p tools.t02_lifecycle_pytest_plugin -c pyproject.toml tests/test_benchmark_suite.py tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race tests/test_surface_benchmarks.py::test_run_benchmark_retains_busy_scratch_without_cleanup_watcher
```

Result: 11 passed in 15.58s. The nine `test_benchmark_suite.py` cases, queue-cancel regression, and scratch-retention selector each emitted `open_managers=[]` after teardown. The scratch-retention selector passed; no diagnostic failure sample was emitted.

This reduced prefix found no manager/thread leakage from `test_benchmark_suite.py` or the directly preceding queue-cancel regression. It omits other `test_surface_benchmarks.py` cases that precede the historical target in the full collection, so it does not rule out contamination from those cases. The bounded evidence narrows the hypothesis to an intra-target timing/state branch or an omitted earlier surface test; it does not identify which, and supports no production source fix.

## Saved combined-run failures and diagnostic stdout contamination

The original T02 assignment records only an unconfirmed combined-suite failure as `2/25 once`; it supplies no 25-node list or original command. The saved `t02-order-control` receipt is a different run: its command executes both whole files (90 tests), and its `attempts_target` is 2. In ordered attempts 1 and 2, and in reverse control, the same two nodes failed. This does not establish the missing original 25-node suite or an order-only failure.

Saved receipt: `C:\Users\Adam\AppData\Local\Temp\t02-order-control-9a7cfc8bd1d543029e8bf05f4423e1fa\receipts\receipt.json`, SHA-256 `A29FFEE6A6CD0BAE1E47BE6F280A9091F53F91A61130F4851B84A33A39D68C3D`. The two node IDs and recorded failure causes:

- `tests/test_surface_benchmarks.py::test_cli_persists_and_reports_baseline_comparison` at line 2602: `json.loads(capsys.readouterr().out)` raised `JSONDecodeError`; captured stdout began with `T02_TRACE={...}`.
- `tests/test_surface_benchmarks.py::test_cli_worker_enforces_wall_timeout_against_real_hung_child` at line 2689: the same JSON parse raised `JSONDecodeError`; captured stdout began with `T02_TRACE={...}` before the valid timeout JSON payload.

The old temporary lifecycle tracer wrote `T02_TRACE` records to stdout while these tests require stdout to contain JSON only. That is direct evidence of test-instrumentation contamination in this saved 90-node run. Its later clean ordered receipt passed 90/90. This separate diagnosis must not be relabeled as the original `2/25` failure.

The candidate lifecycle plugin now writes snapshots to stderr. Exact command for the two affected nodes:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Python313\python.exe -B -m pytest -q -s --tb=short -p no:cacheprovider -p tools.t02_lifecycle_pytest_plugin -c pyproject.toml tests/test_surface_benchmarks.py::test_cli_persists_and_reports_baseline_comparison tests/test_surface_benchmarks.py::test_cli_worker_enforces_wall_timeout_against_real_hung_child
```

Result: 2 passed in 25.41s; after each teardown the plugin reported `open_managers=[]`. The assertions remain unchanged. The exact original 25-node list remains unavailable, so the plugin has not been applied to an invented substitute suite.

Cross-task workload manifest: `handoff/T02-cross-task-dataset-manifest.json`. It pins T10/T11/T15 dataset definitions and source receipts, labels each cold/warm phase, and distinguishes candidate-only measurements from unavailable paired results. Synthetic vector data remains performance-only; semantic quality is unavailable.

Keep all quality targets and acceptance thresholds unchanged. T02 remains open.
