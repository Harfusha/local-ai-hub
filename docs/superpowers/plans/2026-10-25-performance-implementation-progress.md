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
