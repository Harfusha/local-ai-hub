# T02 Quality and Performance Baseline Contract

## Scope

This contract covers offline CPU/index-only synthetic measurements from tools/benchmark_surfaces.py. It excludes model inference. A synthetic benchmark record does not establish real-input retrieval quality, production service quality, GPU inference latency, or live VRAM.

## Plan-grade requirements

A record is plan-grade only when it includes:

- At least 1,000 light samples and 30 paired samples.
- Concurrency levels 1, 4, 16, and 32.
- Six completed workload cases, each with every required golden operation marked passed.
- Cold and warm paired samples suitable for baseline/candidate comparison.
- Matching baseline and candidate metadata and completed matrix; one per-case record is not an aggregate.

The six workload cases are the Cartesian product:

| Files | RAG chunks |
| ---: | ---: |
| 100 | 10,000 |
| 100 | 100,000 |
| 10,000 | 10,000 |
| 10,000 | 100,000 |
| 100,000 | 10,000 |
| 100,000 | 100,000 |

The six workloads each measure concurrency 1, 4, 16, and 32: 24 workload/concurrency cells per baseline or candidate. The source currently labels each execution matrix_aggregation=not_performed_single_case_record and baseline_readiness=per_case. Never relabel a single-case record as plan-grade. See docs/T02-real-input-quality-evidence-plan.md for separate real-input quality evidence requirements.

## Run protocol

Run one workload case per separately owned T20 window. Each case has a 900-second hard limit and fresh external state and scratch directories. Keep offline settings enabled and omit inference.

Phase 1 smoke configuration: files 100, RAG chunks 1,000, concurrency 1, five light samples, one paired sample, fresh state/scratch, per-stage receipt, 120-second hard limit. Do not begin Phase 2 until smoke receipt is complete.

Phase 2 configuration per workload case: --light-repetitions 1000 --paired-repetitions 30 --concurrency 1 4 16 32 --checkpoint <fresh-external-checkpoint> --checkpoint-batch-size 25. Use --resume only to continue the matching checkpoint. Never repeat a completed case.

PowerShell offline environment:

~~~powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
~~~

Command template; replace case values and use new absolute paths outside the repository:

~~~powershell
python -B tools/benchmark_surfaces.py --state-dir <fresh-state-dir> --scratch-dir <fresh-scratch-dir> --files <100-or-10000-or-100000> --rag-chunks <10000-or-100000> --repetitions 3 --full --light-repetitions 1000 --paired-repetitions 30 --concurrency 1 4 16 32 --checkpoint <fresh-checkpoint.json> --checkpoint-batch-size 25
~~~

Each accepted case needs its command, exit status, record/checkpoint paths and hashes, per-stage results, concurrency samples, and golden-operation results. A completed six-case aggregate needs six distinct case entries; baseline/candidate comparison remains a separate receipt.

## Evidence boundaries

Current packet contains synthetic-only results. No real-input quality receipt is attached. No accepted full matrix, plan-grade aggregate, paired baseline/candidate comparison, root-current test receipt, GPU inference result, or live VRAM measurement is attached. GPU/VRAM requires its own explicit T20 scope.

## Preserved historical candidate snapshot (not current acceptance)

The following pre-merge candidate text is retained for provenance. Its commands, hashes, paths and results describe historical work, not verification of this merged checkout. The current master contract above governs execution.

# T02 quality and performance baseline contract

This contract makes a T02 baseline repeatable and comparable. A smoke run, a single size pair, mocked model output, or a provisional record is not acceptance evidence.

## Workload and measurements

- Run the six-case cross product: files `{100, 10000, 100000}` × RAG chunks `{10000, 100000}`.
- Use 1000 light samples, 30 comparison samples, and concurrency `{1, 4, 16, 32}` for every case.
- Keep each run's synthetic state and scratch data outside the repository. Do not copy private project data into benchmark inputs.
- Preserve per-stage cold/warm samples and independent sample identities. Capture p50/p95/p99, throughput, errors, response bytes/token estimates, peak RSS, and VRAM when telemetry exists.
- Require successful transport, validation, index/database, graph, RAG, queue, context-pack, and parent-seed stages. Report skipped hardware telemetry as unavailable, not zero.
- Record these master-plan targets beside the hardware fingerprint: warm `/health` p95 ≤ 50 ms; cached metadata/status/artifact/lease reads p95 ≤ 150 ms; warm symbol/search/code-index p95 ≤ 300 ms on 10,000 files; deterministic-only context pack p95 ≤ 750 ms; warm RAG search without reranker p95 ≤ 750 ms on 100,000 chunks; queue admission p95 ≤ 150 ms.
- Paired comparison uses 10% regression tolerance. Any unexplained cold/warm p95 or p99 regression over 10% blocks acceptance. Inference has no universal latency limit; report queue wait, load time, TTFT, service time, and tokens/s separately.

## Golden and fixture contract

The master plan names symbols, graph, affected tests, retrieval relevance, code generation, vision, and speech. The current runner additionally gates `context_pack`; a plan-grade record must mark all eight operations true in the matrix summary, every matrix row, and each nested case record.

Code-generation, vision, and speech goldens require opted-in inference against the configured Hub. Speech requires a stable local audio fixture plus its exact expected transcript. Accept a fixture only when its audio bytes and transcript are verified and their source/provenance is recorded. Do not substitute mock bytes, metadata-only output, a degraded transcription fallback, or a guessed transcript.

The result may retain the fixture digest, transcript digest, and word count. It must not retain the fixture path or transcript text. The fixture and transcript are inputs to the run, not benchmark-result payload.

## Plan-grade record and comparison

Each saved matrix JSON must have `success: true`, `baseline_readiness: "plan_grade"`, `matrix_aggregation: "complete_six_case_cross_product"`, six unique completed cases, complete golden flags, and no readiness reasons. Keep the emitted `record_path` and SHA-256 with the exact command, UTC timestamp, and HEAD.

For every paired size case, preserve workload, configuration, and hardware fingerprints plus sample provenance. Baseline and candidate must match on `benchmark_scope`, `workload_fingerprint`, `config_fingerprint`, and `hardware_fingerprint`; the implementation fingerprint identifies which source revision produced each record and is expected to change between baseline and candidate.

## PowerShell run sequence

Set `$Config`, `$Audio`, and `$Transcript` to the real configured Hub TOML, verified audio fixture, and exact transcript. The configured state directory must match the config's Hub state directory. Use fresh external scratch paths for the two runs.

```powershell
$Config = '<configured Hub TOML>'
$Audio = '<verified audio fixture>'
$Transcript = '<exact expected transcript>'
$StateDir = '<configured Hub state directory outside the repository>'
$BaselineScratch = Join-Path $env:TEMP 't02-baseline-scratch'
$CandidateScratch = Join-Path $env:TEMP 't02-candidate-scratch'
$Common = @('--state-dir', $StateDir, '--full-matrix', '--inference', '--config', $Config,
    '--speech-fixture', $Audio, '--speech-expected-text', $Transcript, '--timeout-seconds', '3600')

& C:\Python313\python.exe tools\benchmark_surfaces.py @Common --scratch-dir $BaselineScratch
# Save the emitted record_path as $BaselineRecord, then record its SHA-256.

& C:\Python313\python.exe tools\benchmark_surfaces.py @Common --scratch-dir $CandidateScratch --compare-with $BaselineRecord
# Save the emitted candidate record_path and SHA-256; retain all six case comparisons.
```

Do not call the pair comparable unless both records pass the plan-grade gates and all six cases have comparison results. Keep failed and timed-out attempts as evidence; do not overwrite them with a later passing run.

## Regression verification order

After T13 reports GREEN, first confirm the delayed-dispatch fix and persisted-schema change are present in the T02 candidate. A T13 receipt from another HEAD or `async_jobs.py` hash does not clear this gate. Pin the T02 HEAD and input hashes. After T20 assigns the exclusive slot, run the direct queue-race selector on that candidate, then the benchmark lifecycle and matrix selectors. The repeat utility is supplementary. Do not use its 25 repetitions as the original flaky-suite acceptance: the original report describes a combined 25-node set with two failures, while this utility runs both whole files (90 collected tests in the saved receipt). The exact original node list/command is still missing. Recover it before any reproduction; do not substitute a guessed list or blindly repeat the 90-node suite.

```powershell
$ReceiptDir = Join-Path $env:TEMP ("t02-repeat-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& C:\Python313\python.exe tools\repeat_t02_pytest.py --python C:\Python313\python.exe `
    --out-dir $ReceiptDir --attempts 25 --timeout-seconds 180 --reverse-control
```

If a separate repeatability study is requested, the utility saves one `receipt.json` plus per-attempt stdout/stderr logs. Receipt field `schema_file` points to JSON schema [t02-pytest-repeat-v1.schema.json](../tools/schemas/t02-pytest-repeat-v1.schema.json). Receipt version `t02-pytest-repeat/v1` pins HEAD, branch, Python/platform, dirty paths, input SHA-256 values, argv, duration, timeout, exit code, failed node IDs, and log hashes. Output directory must be new and outside the repository. Preserve each run; utility refuses to overwrite evidence.

Current pending selectors:

```powershell
C:\Python313\python.exe -m pytest -q --tb=short tests/test_surface_benchmarks.py::test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race
C:\Python313\python.exe -m pytest -q --tb=short tests/test_t02_repeat_pytest.py
C:\Python313\python.exe -m pytest -q --tb=short tests/test_surface_benchmarks.py::test_run_benchmark_is_isolated_and_preserves_existing_scratch_data
C:\Python313\python.exe -m pytest -q --tb=short tests/test_surface_benchmarks.py::test_full_matrix_persists_cases_and_compares_each_size_pair
```

The current stored single-case receipt is failed and provisional; it is not a baseline for this contract. The queue-cancellation race is owned by T13 and must be repaired in its owner's scope before the repeated verification sequence.
