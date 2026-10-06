# T02 Combined-suite Flake Evidence

Date: 2026-10-01 (Europe/Prague)

## Historical T02 combined suite

Candidate HEAD: `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`.

Exact recorded command:

```powershell
C:\Python313\python.exe -m pytest -q --tb=short tests/test_benchmark_suite.py tests/test_surface_benchmarks.py
```

Historical receipt: `C:\Users\Adam\AppData\Local\Temp\codex-t02-flake-20260930T201729-b78b0be9.json`, SHA-256 `F602295B4B953034F4DADACE78AF297E448FD4AA8DA28343BCB7C091B4D07FE2`. Receipt recorded 3 of intended 25 attempts; all 3 failed. Results: 78 passed/11 failed/2 errors; 89 passed/1 failed; 83 passed/7 failed/1 error. Queue selector failed each time: `cancel()` observed `running`, expected `cancelled`. Runs 1 and 3 also had scratch cleanup/orphan errors. Reverse-order control absent; do not infer a completed 25-run rate.

Historical test hashes: `tests/test_benchmark_suite.py` `39b663c125da4714348dab5d39c2fd42832331f1617dfb64c5709f1a5940b8f6`; `tests/test_surface_benchmarks.py` `a2a577ee95bb7fa9057f1c03bdb1a61957f6e6e45dd5ebe5ec4eca1c43014f4b`.

Current candidate HEAD matches historical HEAD. Current `test_benchmark_suite.py` hash matches; current `test_surface_benchmarks.py` hash is `5AA53B487B91E42B185853EBA2F06502A43D37A9DD78EE7BC4D5A74DDA122FAC`, different from historical `A2A577EE…3014F4B`. Exact historical snapshot is therefore unavailable. Do not claim a same-snapshot reproduction.

## Root-cause evidence from historical output

- The delayed-dispatch queue selector failed in all three attempts: `cancel()` returned `running`, expected `cancelled`.
- Attempt 1's benchmark diagnostic recorded a failed `hub_queue_admission` candidate stage, a live daemon worker `async-job-fe63de95` after baseline close, and no SQLite operational errors. The later scratch-retention test failed because that worker was still alive. Attempts 1 and 3 then raised `benchmark scratch cleanup is still pending`; attempt 3 recorded the analogous live worker `async-job-b6bb8fe2`.
- This supports a concrete race chain in the historical implementation: a queued row became visible before delayed-timer registration; an intervening `tick()` dispatched it; cancellation then observed `running`. The benchmark admission gate failed while the worker remained live. Scratch cleanup correctly retained the directory, and later benchmark invocations failed while that retained worker remained active. Attempt 1 and 3 cascades were 11 failures/2 errors and 7 failures/1 error; attempt 2 had only the queue failure.
- Current candidate source persists `dispatch_not_before`, filters `tick()` to due queued rows, and conditionally claims dispatch. The current regression test injects `tick()` in the insert-to-timer gap. A prior isolated pass predates the current combined-suite snapshot and does not prove this suite is stable.
- Receipt `reverse_control` is null. Test-order amplification remains unverified. Run bounded ordered repeats plus reverse control only after T20 releases the shared slot and command broker supplies an authorized receipt.

## Current candidate replay pin

- Candidate HEAD: `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`.
- Input SHA-256: `tools/benchmark_surfaces.py` `D00810615257B654B894A0B9ECB4E4C36E9B130031AC3F1C8A37D5D87873B413`; `tests/test_benchmark_suite.py` `39B663C125DA4714348DAB5D39C2FD42832331F1617DFB64C5709F1A5940B8F6`; `tests/test_surface_benchmarks.py` `5AA53B487B91E42B185853EBA2F06502A43D37A9DD78EE7BC4D5A74DDA122FAC`; `src/local_ai_hub/async_jobs.py` `6C245F4A52C4D1FD2A0D5AC50DFA6CE3E018B9CD2A400F27241690CC8BC97F0A`; repeat utility `D68A6D761C7A3B80D44B5B8F9BF6B268521D30D04E9D77609C34C0B2B91017CE`.
- The earlier proposed three-run diagnostic was superseded by the completed 25-attempt replay below. Formal acceptance still requires all four selectors above before the 25-attempt run; one failed repetition leaves acceptance incomplete.

## Incorrect T12 selector replay (not T02 evidence)

One later command mistakenly used five T12 selectors against `C:\Users\Adam\.codex\worktrees\4816\.local-ai-hub\tests\test_t12_benchmark_contract.py`. Current test-file SHA was `39A48EA373E291F03BC4F660A4EF892C5526A6FC3DD822F5722D4586953E583B`. Pytest exited 1 during collection: four selectors not found, `no tests ran in 0.16s`. No assertions ran. This did not reproduce or test the T02 flake; no further selector run made.

## T02 handoff

Candidate patch: `handoff/T02-owned-current-root.patch`, SHA-256 `4EA768F0BFF617314DEABC8CACE4FEBD866C89905522C173724113FFE40A0DE9`. Current root comparison shows the T02 payload present in all six paths: five files match candidate text; `tools/benchmark_surfaces.py` has a separate 35-line T12 helper. Do not reapply the stale patch. Focused T12 preservation proof was sent to T20: prior root T12 tail SHA-256 `AF9E34AA0E10CB619068AD5239C02F2C594F1C9D8962E1CA333974BFDFE9E529`.


## Current candidate replay (2026-10-01)

Candidate HEAD and source pins remain those listed above. Exact combined command:

```powershell
C:\Python313\python.exe tools\repeat_t02_pytest.py --out-dir C:\Users\Adam\AppData\Local\Temp\t02-25-7117a0910dab4182b039eb030be65540\combined --python C:\Python313\python.exe --attempts 25 --timeout-seconds 180 --reverse-control
```

- Prerequisite selector batch passed 12/12 in 25.18s; log SHA-256 `51FAFF9117D2DD70B1C0D121B0E2D27BC8DC827509513B53170F84B04F7656E8`.
- Ordered runs 1–19 passed 90/90. Ordered run 20 passed 89/90 in 109.43s, then failed `tests/test_surface_benchmarks.py::test_run_benchmark_retains_busy_scratch_without_cleanup_watcher`. Assertion at line 888: `result["success"] is True`; diagnostic stage: `failed_stages=['hub_queue_admission']`. The assertion precedes lines 889–908, which contain scratch existence, no-watcher, retained-count, and second-run refusal checks. Therefore the run records a queue-admission precondition failure, not a failed scratch-retention assertion.
- Attempt 21 was spawned but killed before producing output or receipt; it is aborted and unscored. Attempts 22–25 did not run. This is not a completed 25-attempt acceptance pass.
- Isolated benchmark control passed 9/9. Isolated surface control passed 80/81 with the same scratch-retention selector failing. Reverse-order combined control passed 90/90. Queue-cancel regression selector passed in all 20 completed ordered runs and reverse control. The failing trace recorded `shutdown=true`, no worker or delayed-dispatch threads, and one `outcome_unknown` row at close; this does not explain the admission-stage result.
- Confirmed boundary: only `hub_queue_admission` stage failed; test stopped before scratch-retention assertions. Close trace shows `shutdown=true`, no live workers/delayed dispatch, nine cancelled probe rows, and one `outcome_unknown` row consistent with the fixture sentinel. Eight captured cancel responses were successful and `cancelled`. Pytest locals omit per-sample stage reasons; saved evidence does not identify failed sample or distinguish submit rejection, running cancellation, or caught exception. Timing/order remains a hypothesis. Historical delayed-dispatch race is not proven cause here.
- Tracer emitted to stderr only; corrected tracer SHA-256 `DF79281E3023B929A9B00572651A6C327D4D788A8A13A9A5C5B39C0028B234B7`. Ordered-20 stdout SHA-256 `C13A6C71FD492B9888C6697EC917F14E8AA2351D702B8CAE3004C72D7B2C8FDF`; stderr SHA-256 `962636E4CC52143A9409CE9F3CC31AA5A41FAEC7A37C9A2A39E7398EC78E538C`.
- Evidence summary `C:\Users\Adam\AppData\Local\Temp\t02-25-7117a0910dab4182b039eb030be65540\evidence-summary.json`, SHA-256 `6A5659520243E887A5003ED53017C3EC4C16C241267A4FA19F8A6BEF36268905`. Partial receipt SHA-256 `F0089AD94BB75A5FC8879E81523798E53C06FA467D528CCD5EAD3967C73CB5F4`; environment manifest SHA-256 `4FCC3EEE4C61C077D55192DA7FF75DC0EA88CB83D65095909D9B3C2808A84250`.
- No source or assertion changed during this replay. Do not weaken acceptance criteria. Diagnose saved logs before a future test window.
