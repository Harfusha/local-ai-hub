# T02 Original `2/25` Forensics — 2026-10-01 v2

## Read-only scope

This note reviews the saved `t02-order-control` receipt/logs and the two affected test/source blocks. No test, benchmark, or load command was run. No root source or T20 slot was touched. Earlier published handoff files remain unchanged; this is a versioned addendum.

## The recorded two failures

The saved receipt is `C:\Users\Adam\AppData\Local\Temp\t02-order-control-9a7cfc8bd1d543029e8bf05f4423e1fa\receipts\receipt.json`, SHA-256 `A29FFEE6A6CD0BAE1E47BE6F280A9091F53F91A61130F4851B84A33A39D68C3D`.

All three recorded executions of the two whole test files (88 passed, the same 2 failed) contain these node IDs:

1. `tests/test_surface_benchmarks.py::test_cli_persists_and_reports_baseline_comparison` — source line 2602, `json.loads(capsys.readouterr().out)` raises `JSONDecodeError: Expecting value`.
2. `tests/test_surface_benchmarks.py::test_cli_worker_enforces_wall_timeout_against_real_hung_child` — source line 2689, the same parse raises `JSONDecodeError: Expecting value`.

For both tests, the captured `capsys` stdout begins with a `T02_TRACE=` record instead of JSON. In the timeout test the valid timeout JSON follows that trace record. All three run receipts have empty stderr logs (SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`) while their stdout logs contain `T02_TRACE` records. Thus the direct cause of these two saved assertion failures is instrumentation text contaminating stdout, which the tests reserve for JSON.

The same two failures occur in ordered runs 1 and 2 and in the reverse-order control. This saved study therefore does not support an order-dependent explanation for these two node failures. It also is not the original 25-node list: it ran both complete files, 90 collected tests, with `attempts_target=2`.

## Cause boundary

- **Confirmed immediate failure mechanism:** non-JSON `T02_TRACE` text reached captured stdout before the JSON payload.
- **Not supported for these two nodes:** an AsyncJobManager shared-state leak, scratch cleanup failure, or order-only defect. The failure sites are JSON parsing, and the same nodes fail in reverse order.
- **Unconfirmed instrumentation provenance:** the saved receipt hashes test/runtime inputs but does not hash the temporary tracer. The tracer file currently at `...\plugin\t02_trace_plugin.py` is SHA-256 `DF79281E3023B929A9B00572651A6C327D4D788A8A13A9A5C5B39C0028B234B7` and currently directs its print to stderr; that current file cannot be treated as the exact historical stdout-writing version. The logs prove contamination, but not which environment/plugin revision routed it to stdout.
- **Original assignment remains unverified:** `2/25 once` lacks its exact node list, command, and original tracebacks. Do not claim this separate 90-test instrumentation finding closes that original RCA.

The candidate lifecycle plugin now emits `T02_LIFECYCLE` snapshots to stderr (`tools/t02_lifecycle_pytest_plugin.py`, `pytest_runtest_logreport`). Its previously saved two-selector candidate pass is useful evidence for the corrected candidate harness, not proof of root integration or the original 25-node RCA.

## One bounded root gate for T20

When T20 schedules the next root correctness gate, run this two-selector batch once, in the order shown, with the current stderr-only lifecycle plugin. Do not run the contaminated whole-file matrix as a substitute; do not claim timing/performance acceptance from it.

```powershell
C:\Python313\python.exe -B -m pytest -q -s --tb=short -p no:cacheprovider -p tools.t02_lifecycle_pytest_plugin -c pyproject.toml tests/test_surface_benchmarks.py::test_cli_persists_and_reports_baseline_comparison tests/test_surface_benchmarks.py::test_cli_worker_enforces_wall_timeout_against_real_hung_child
```

This targeted gate checks that JSON-only stdout remains intact under the current lifecycle instrumentation. Its result would not recover the missing original 25-node list or finish T02's plan-grade/performance baseline.
