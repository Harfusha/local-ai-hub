# T02 selector timeout attribution — 2026-10-01

## Finding

The 120-second timeout occurred after pytest collection and inside the first selected test's benchmark work, not during pytest startup or collection. This is not enough evidence to call it an async leak or to call the historical SQLite warning fixed.

## Evidence

- Receipt records Python 3.13.2, two collected selectors, explicit isolated pytest `--basetemp`, 120-second timeout, status `timeout`, exit 124.
- Captured stdout stops at `T02_BASELINE_RESULT={"failed_stages":[],"stage_failures":{},"success":true}`. That line is emitted after the first `run_benchmark` returns at `tests/test_surface_benchmarks.py:1262`.
- Test then validates baseline record and invokes its second comparison `run_benchmark` at `tests/test_surface_benchmarks.py:1459`. No candidate result or teardown marker was captured before timeout. Pytest's teardown `T02_DIAGNOSTIC` finalizer is registered at line 1229.
- Isolated state contains first successful record `pytest-state-root/test_run_benchmark_is_isolated0/state/surface-benchmark-1790875919033859500.json` (`success=true`, no failed stages) and a retained second-run synthetic workspace `synthetic/local-ai-hub-benchmark-_74bdsh9`.
- Read-only SQLite snapshot of that retained workspace's `async_jobs.sqlite3` found 9 jobs, all `cancelled`; no `running` state. This does not provide thread-liveness evidence because runner killed pytest at timeout before finalizers.
- Captured stdout/stderr contain zero `ResourceWarning` mentions. Forced process termination can prevent warning/destructor/finalizer output, so absence is inconclusive.

## Classification

Pytest harness startup/collection is not the hang. First baseline benchmark completed. Non-return is localized to the selected test's second comparison benchmark, subject to the 120-second cutoff; no finer stage evidence exists. No source expectation changed. No test rerun, 25x loop, benchmark matrix, or root write performed during this attribution.

## Artifact hashes

- stdout SHA-256 `b84fb836832fdd2e46503abe3712d6b1d9ac0767898d009987ce47038dd19a6c`
- stderr SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- receipt SHA-256 `286eb1689a28c573598a00efcc398862ae7ecd092c75b25844decec392d29955`
