# T15 command broker benchmark runbook

## Gate

Do not run this harness against the current dirty candidate. T20's current queue: T07, then T04 in correctness slot 07, then T15 in correctness slot 08; the paired benchmark gets a later separate slot. Run only after T20 provides the owner-scoped integrated candidate revision and explicit benchmark slot. Integrated T15 revision is not confirmed. No benchmark was run while preparing this runbook.

## Revision-matched protocol

For each required CPU/hardware profile, run baseline and integrated candidate as separate clean checkouts. Invoke same committed v2 harness from a clean harness checkout, passing `--root` and that checkout's exact `--expected-commands-sha256`. The runner compares raw `commands.py` bytes to the explicit pin before importing the selected source tree, then repeats source, execution, and harness identity checks after measurement. Pin commit IDs; record harness checkout and selected source/execution HEADs; require each selected checkout to stay unchanged during its run. Save full `commands.py` and harness SHA-256 values before and after. Use same Python, Git, broker-selected shell, OS, hardware profile, benchmark config, command set, and harness SHA within each paired comparison. V2 rejects dirty harness, source, or execution checkouts; only clean runs are eligible as acceptance evidence.

Use a fresh output path outside harness, source, and benchmark repositories. Example command template per source revision (not executed):

```powershell
python -B tools/benchmark_command_broker.py --root <baseline-or-candidate-checkout> --expected-commands-sha256 <exact-raw-commands.py-sha256> --light-samples 1000 --paired-runs 30 --pair-order-seed 731 --output <fresh-path-outside-all-repositories.json>
```

Keep the same seed for baseline/candidate; repeat with a separately recorded seed if order sensitivity remains material. Harness schema v2 randomizes a balanced hit-first/miss-first order, records every pair and reports each order stratum separately. Forced misses and warm hits now run the same `git status --short` command with the same tenant; the previous Python sleep miss was not a comparable cache-miss sample. The harness records broker-matched shell resolution and rejects source or execution repository changes during a run.

Measure cache hit/miss p50, p95, p99 and raw order strata; concurrent warm hits; single-flight owner/waiter/execution counts; structured and shell startup; dual-stream capture with callback enabled and disabled; output byte counts and callback drops; peak-memory/platform metadata. Each paired cache fixture now requires boolean outcome for seed and every sample, reports expected/observed hit and miss counts, records the seed separately, and emits command/tenant/seed/order fixture metadata plus per-pair outcomes. Concurrent warm-cache receipts include every index, elapsed time in milliseconds, and boolean outcome, alongside expected/observed hits, misses, classified calls, worker count, and the separately verified seed miss. The output records `light_samples_per_concurrency` and `pair_order_seed`, so the fixture can be reproduced with the same parameters. Acceptance requires exactly `N` hits and `N` misses for `N` pairs; each concurrency level requires `light_samples` hits, zero misses, and `classified_calls=light_samples`, excluding its seed miss. Missing classifications fail the run. Regression selectors are recorded in `t15-acceptance-evidence.json`; do not run them before T20 assigns the slot. The single-flight fixture keeps its separate slow command and hard-fails unless each batch reports exactly one owner, `workers - 1` waiters, and one execution.

Acceptance: demonstrate at least 25% p95 or peak-memory improvement on the identified bottleneck; no unexcused warm/cold p95 or p99 regression above 10%; explain order-stratum differences; meet the master plan's required CPU/hardware profiles. Current saved v1 reports are historical and do not satisfy this gate.

## Write-set rollback and concurrency findings

Read-only review of the available candidate source found write-set path validation, but remaining rollback proof belongs to T06 and is not changed by T15:

- `CommandBroker.patch_and_verify` may return `applied: false`, `rolled_back: false`, and `rollback_error` after an apply failure. Without an explicit unknown-state result/incident, callers may retry while repository state is uncertain.
- `git apply --check` and `git apply` timeout paths were reported uncaught; timeout can escape before rollback or an uncertainty result.
- A successful forward `git apply --check` after reverse-check failure is not proof the working tree was restored; verify post-state against the pre-apply write-set snapshot.
- Direct-run restore failure paths were reported to omit `outcome_unknown` and rollback-failure incident publication.
- T06's latest review is also checking rollback check/publish races and daemon task ownership. `commands.py`, T06 tests, and rollback implementation remain T06-owned; T15 will not edit them.

Existing cache/single-flight receipts cover policy identity, bypass behavior, waiter result publication, and cross-broker suppression. Harness regression tests added in `tests/test_benchmark_command_broker.py` cover balanced reproducible order, order-stratified summaries, shell selection, same-command hit/miss pairs, and callback/no-callback capture fixtures. They were not run because T20 has not assigned the validation slot.
