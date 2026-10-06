# T02 Resume Evidence Packet v3 — 2026-10-04

## Worktree audit

- Candidate root: `C:\Users\Adam\.codex\worktrees\t02-quality-baseline-resume\.local-ai-hub`
- Candidate HEAD: `ad974c54e150d5f2c9bdada8179bc02457147549` (detached).
- Candidate has untracked prior T02 docs, handoffs, repeat-runner, and evidence; owned matrix runner paths also untracked. No tracked candidate file was modified in this continuation. No commit created.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
- Root `tools/run_t02_matrix.py` and `tests/test_t02_matrix_runner.py` are absent. Root async implementation/tests are dirty and match the exact postimages in the existing T02 async patch; do not infer tests passed from hashes.

## Current owned candidate payload

| Path | Candidate SHA-256 |
|---|---|
| `tools/run_t02_matrix.py` | `95357BE1D1F228AECE342AB62208DA4B0F6C525B57C19B87364B9F5C44570783` |
| `tests/test_t02_matrix_runner.py` | `77366AB34F1BE2047B82E2438DE7BF1B13C86DA0A47440AD1CE4C83D09D3A0DC` |

Patch: `artifacts/t02-matrix-runner-integration-20261004-v3.patch`, SHA-256 `FB104161A28FFDF56757BF9CCABE22364C158398D3C09F7B89840C89B02BA15D`. Root `git apply --check` passed. It contains two new files only, 637 insertions; not applied.

Manifest: `artifacts/t02-matrix-runner-manifest-20261004-v3.json`, SHA-256 `9ADBCDF97A553C84880A925B99DF4BB1A8CEB50DFF84361C37320AC3231A47E3`.

## Actual candidate evidence

- Exact command: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_t02_matrix_runner.py`
- Result: **10 passed in 0.23s**, exit 0. Includes a mocked orchestration contract that checks six invocation/receipt paths and 24-row aggregation plumbing; it is a unit check, not measured performance acceptance.
- Checkpoint selector: `python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_surface_benchmarks.py::test_benchmark_checkpoint_resumes_completed_stages_and_incomplete_progress` → **1 passed in 0.13s**.
- Actual smoke only: `(100 files, 10,000 RAG chunks)`, repetitions 3, light 10, paired 3, concurrency 1/4/16/32, `--full`, no inference. Exact command and paths are in `artifacts/t02-smoke-100-10000-20261004-v1.json`; receipt SHA-256 `A4C801E5B5EFFCE746B882601F67FD934796D2FC6EF4D70CED7565FBF0D5627A`. Raw record outside repo: `C:\Users\Adam\.codex\worktrees\t02-evidence-20261004\state\surface-benchmark-1791131666250847500.json`, SHA-256 `F00B458DF9EBDCB839CEB93A64B8ECC64BBF7B20B111804CC38EF56D8EFFA927`; exit 0, 46,770.644 ms. Queue: 530 samples, p50 987.085 ms, p95 5,899.735 ms, zero errors. Record says `baseline_readiness=per_case`; it is synthetic-only smoke.

## Root/current acceptance boundary

- No root test or benchmark ran in this turn, per instruction.
- Previous T20 one-shot root matrix-persistence selector passed 5/5 in 15.00s; test uses fake benchmark records, so it proves persistence logic only, not actual matrix performance.
- Root current async source/test SHA-256: `async_jobs.py` `98C5E08B35AEB72AE67C838287A3AC83646BC46CCC9437660B5F285C55B814D3`; `test_async_jobs.py` `DD27B2537AE7AC08D97DB4D450EB073915397404B7C97D640712D16AC903CEBE`; coordination test `5936A76040E1C42DE53FDA91874D0E927D7955591BA980D9DAD9C90E5C3864E9`. These equal async patch postimages; root-current acceptance test remains unrun here.

## Reported 2/25 flake

The old report says 2 failures in 25 attempts, but contains no failing logs, attempt numbers, or exact revision; attribution to the delayed-dispatch cancellation race is unproven. Later candidate evidence for `tests/test_async_jobs.py::test_early_delayed_dispatch_callback_preserves_queued_cancellation` is one pass plus 25/25 serial fresh-basetemp repetitions (receipt SHA-256 `A7E789B2EAFEF82645AEC6797794A8EC652FA893D2E456399D3040B55519BE37`). That demonstrates stability in the later run only; it does not identify or resolve the historical two failures. Do not count expectation/runner unit tests as reproductions of the old flake.

## Remaining blockers

- Full acceptance remains unrun: 24 cells across six file/RAG sizes × four concurrency levels, with 1,000 light and 30 paired samples per workload.
- Real-input retrieval quality remains unmeasured; corpus, queries, labels, and thresholds lack T20 approval. Synthetic checks are not a substitute.
- Paired baseline/candidate and complete root-current acceptance are absent. Root tests remain prohibited for this turn.