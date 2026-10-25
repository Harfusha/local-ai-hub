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

## Next gates

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

Finish T0a sample timing/diagnostics, current-source owned matrix and measurement
contracts; execute Windows native experiment, then whole indexing A/B before any
native adoption. T0c adapters and T1–T12 remain open. Do not claim current release,
deployment, model quality, full suite or all-24 completion from this block.
