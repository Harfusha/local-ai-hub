# T15 source-pin and benchmark-slot preflight — 2026-10-02

## Result

**BLOCKED — no T20 clean integrated pin or explicit T15 slot received yet. No benchmark or test was run in this audit.** T02's CPU slot release is acknowledged, but the runbook requires both source pins and T20's explicit assignment; the slot release alone is not authorization.

## Current ownership and dirty state

- Assigned candidate: `C:\Users\Adam\.codex\worktrees\t15-command-config\.local-ai-hub`, detached `HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`, **66 dirty paths** at preflight. Preserve all current state. `src/local_ai_hub/commands.py`, `project_config.py`, and `services.py` contain owner/shared changes; no source edits made here.
- Root: `C:\Users\Adam\.local-ai-hub`, `master` at `01df56605ccf484ebfe2808ac60d696c4e81dffc`, **348 dirty paths**. Root sources remain T20/T06/T21-owned; no root changes made here.

## Pins do not qualify for a run

| Input | Candidate/current SHA-256 | Root/current SHA-256 | Result |
|---|---|---|---|
| `src/local_ai_hub/commands.py` | `AAE990BF1D80271EABC392C839A1CCA388694011A768F97040FB1AB2B453F567` | `DC125391DC6BC06C8C5777018E524230233E41E68D09894174D66E6BABF0344E` | differ; both dirty |
| `src/local_ai_hub/project_config.py` | `EEC7E2920ED905E902D3699A5259D19E23EF9D4B7F17A285E160E97F63EC4686` | `4238B6A6DE1DE00F55F4679CE0DF7D431522EC1BAFABFA272258C1662F13F713` | differ; both dirty |
| `src/local_ai_hub/services.py` | `7394F38919B5F3B421110C6CB88E841D386CC8B6C848C410B501549AB4029ADD` | `CCD292C8F91809B59BD3446D045CB550BABBD8CAEA86FAB4FCAA6D2E284564A0` | differ; both dirty |
| runbook v2 harness `tools/benchmark_command_broker.py` | `8AEF9B315B44B1A15BAD0A52B79213F2F4A319E6BCD84DDA240778F2C32930AB` | `28F0F793960FFB0EC811A6E828EA8211B958C828522793ED4F801D16F66C1687` | differ; untracked in both checkouts |

The existing pin-preflight file is stale: it records root `98a9a1a` (current root is `01df566`), baseline/candidate dirty counts 13, and no clean candidate receipt. The current candidate status count is 66. The source-tree baseline commit `824c9eb` has a clean Git tree, but its harness is absent and it is not the integrated candidate pin. The current baseline/current files therefore cannot form a revision-matched paired comparison.

## Runbook and old evidence

- `handoff/t15-command-broker-benchmark-runbook.md`, SHA-256 `23C46071974642473E0D440CAE4FBA594478370705F6319BCC230DAF0BA7326F`: requires separate clean baseline/integrated checkouts, the same committed harness and runtime/config profile, unchanged source pins before/after, randomized paired runs, and two CPU/hardware profiles. Acceptance threshold: at least 25% p95 or peak-memory improvement, with no unexplained warm/cold p95/p99 regression above 10%.
- Correct v2 harness path is `tools/benchmark_command_broker.py`; candidate SHA is `8AEF9B…`. It is untracked; `clean_harness_sha_assigned=false`. `tools/t15_paired_benchmark.py` is a separate contract harness, not the runbook's v2 performance runner.
- Historical config-parity microbench: 7 pairs; root median 48.3118 ms, candidate 62.8292 ms, candidate +30%, `acceptance=false`. It uses differing T06/T21 source trees and is not command-broker performance acceptance.
- Earlier T15 contract command was `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_t15_paired_benchmark_contract.py tests/test_benchmark_command_broker.py` → **26 passed in 2.97s**. That is an older receipt: its manifest pins `commands.py` to `bfbcab…`, while current candidate is `AAE990…`. The runbook says do not run its regression selectors before T20's assignment, so I did not repeat them.

## T20 request

Asked T20 for clean baseline/integrated commit SHA, exact `commands.py`/`project_config.py`/`services.py` source pins, one shared committed v2 harness SHA, two profile definitions, and explicit exclusive CPU-slot start windows. Request sent; T20 remained active and did not answer during one bounded wait. Benchmark remains **NOT RUN**.

## Hub status

Local AI Hub preprocess/context requests failed before write; one bounded status check returned `success=false`. Native read-only audit used as the bounded fallback. No further Hub retry, benchmark, or test run.
