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
