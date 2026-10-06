# T02 Admission Flake Forensics — 2026-10-01 v1

## Scope and evidence boundary

Read-only review of the owned T02 handoff and saved run artifacts. No benchmark, load, model, or repeated test command was run for this note. No source, root, or T20-owned slot was changed or used.

Candidate revision: `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`.

## Keep the two histories separate

- The original assignment's `2/25 once` report still has no recoverable exact 25-node list, original command, or two-node traceback set in the owned receipts. A historical receipt records three attempts over the two whole test files, all three failed, with the delayed-dispatch cancel selector returning `running` instead of `cancelled`; this is not the missing original 25-node list.
- A separate later study attempted 25 ordered executions of the two whole files (90 tests per execution). It completed 20 ordered attempts: runs 1–19 passed 90/90; run 20 failed 89/90 at `test_run_benchmark_retains_busy_scratch_without_cleanup_watcher`; run 21 was spawned then terminated before a receipt; runs 22–25 did not run. This is not a completed 25-attempt acceptance run and does not reconstruct the original 25-node set.

## Run-20 observations

Source artifacts:

- Evidence summary: `C:\Users\Adam\AppData\Local\Temp\t02-25-7117a0910dab4182b039eb030be65540\evidence-summary.json`, SHA-256 `6A5659520243E887A5003ED53017C3EC4C16C241267A4FA19F8A6BEF36268905`.
- Partial receipt: `C:\Users\Adam\AppData\Local\Temp\t02-25-7117a0910dab4182b039eb030be65540\partial-receipt.json`, SHA-256 `F0089AD94BB75A5FC8879E81523798E53C06FA467D528CCD5EAD3967C73CB5F4`.
- `ordered-20.stdout.log`, SHA-256 `C13A6C71FD492B9888C6697EC917F14E8AA2351D702B8CAE3004C72D7B2C8FDF`.
- `ordered-20.stderr.log`, SHA-256 `962636E4CC52143A9409CE9F3CC31AA5A41FAEC7A37C9A2A39E7398EC78E538C`.

Observed facts:

1. Pytest failed at line 888 on `assert result["success"] is True`. The returned benchmark result identified `failed_stages=["hub_queue_admission"]`. The test stopped before its scratch-retention assertions.
2. The saved trace contains eight queue-probe cancellations; each returned `success=true`, `state=cancelled`, `terminal=true`, and `admission_state=accepted`.
3. The controlled sentinel worker was intentionally alive before manager close. The close trace's final state had `shutdown=true`, zero live threads, no delayed IDs, nine cancelled rows, and one `outcome_unknown` row. This is teardown evidence; it does not explain why the queue-admission stage result was false.
4. The per-sample `failed_samples`/error reasons are not present in the saved receipt or captured pytest locals. The evidence summary explicitly records `confirmed_cause=false`; timing/order interaction and stderr tracing remain hypotheses.
5. Isolated benchmark tests passed 9/9. Isolated surface tests passed 80/81 with the same selector failing. Reverse-order combined control passed 90/90. The queue-cancel selector passed in all 20 completed ordered attempts and in reverse control.

## RCA disposition

The later run-20 failure is **observed but not root-caused**. It is distinct from the earlier historical cancel-race evidence: in this run, saved queue-cancel probes succeeded, while the aggregate `hub_queue_admission` stage still failed. The current evidence does not identify the failed sample or establish a single cause across these incidents. No code fix or acceptance downgrade is justified by this record.

The original 25-node report remains unresolved. Any future reproduction or additional sample capture must wait for an explicit T20 test-slot release; this note does not authorize one.
