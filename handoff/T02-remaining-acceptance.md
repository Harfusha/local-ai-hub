# T02 Remaining Acceptance

## Candidate ownership

- Worktree: C:\Users\Adam\.codex\worktrees\t02-quality-baseline-resume\.local-ai-hub
- Verified before this documentation/harness edit: clean detached HEAD ad974c54e150d5f2c9bdada8179bc02457147549.
- Candidate source ancestry includes async fix f8024d8ebb51c9bca68e9d8fdaf68c2491b0b1f9 over root baseline 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf.
- Other temp worktree for branch task_2d1d72257ea5 is outside this worktree; it was not modified.
- No root checkout writes.

## Accepted evidence already recorded

- Checkpoint resume selector: 1 passed in 0.19s.
- Scratch isolation selector: 1 passed in 19.51s.
- Plan-grade and cold/warm comparison selectors: 2 passed in 0.14s.
- Async recovery/reopen/eviction selectors: each 1 passed.
- Delayed-dispatch cancellation regression: passed once plus 25 serial fresh-basetemp repetitions. Receipt JSON SHA-256: A7E789B2EAFEF82645AEC6797794A8EC652FA893D2E456399D3040B55519BE37.
- Earlier entries are prior candidate receipts. Current authorized isolated harness command: python -B -W error::ResourceWarning -m pytest -q -p no:cacheprovider --tb=short tests/test_t02_repeat_pytest.py
- Result: exit 0, 3 passed in 0.09s. Selectors: bounded repeat count, external output directory, and fixed allowlisted pytest command.
- This was the only test invocation in this edit. No 25-run replay, broad suite, benchmark, GPU inference, or root test was run.

## Benchmark status

Earlier synthetic run was interrupted after more than ten minutes:

- Command: python tools/benchmark_surfaces.py --state-dir <fresh> --scratch-dir <fresh> --files 100 --rag-chunks 1000 --repetitions 3 --light-repetitions 1000 --paired-repetitions 30 --concurrency 1 4
- Result: exit 1 after Ctrl+C; 4,756/5,000 queue rows (95.12%), all cancelled; 30 evidence rows; no persisted timing samples or stage summary.
- This is incomplete progress, not an accepted performance result.

Open receipts:

1. Complete six-workload by four-concurrency CPU/index-only matrix (24 cells; four concurrency series per workload): (files, RAG chunks) = (100, 10,000), (100, 100,000), (10,000, 10,000), (10,000, 100,000), (100,000, 10,000), (100,000, 100,000).
2. Concurrency 1/4/16/32 with 1,000 light and 30 paired samples per accepted run.
3. Smoke receipt before Phase 2, followed by one owned matrix case per T20 window, max 900 seconds each.
4. Completed matrix aggregation; current benchmark emits matrix_aggregation=not_performed_single_case_record and baseline_readiness=per_case.
5. Paired plan-grade baseline/candidate comparison.
6. Real-input retrieval/quality receipt per docs/T02-real-input-quality-evidence-plan.md. Current packet is synthetic-only; no real-input quality is established.
7. Root-current test receipt.
8. GPU inference and live VRAM receipts; separate explicit T20 scope required.

## Root-current integration packet

Existing candidate artifacts:

- Patch: artifacts/t02-root-current-async.patch
- Patch SHA-256: 9BF1C38E0A0C7E4CD6CCDAA13640525883A0C0859DDA676BA5BF5FE5E50ADA3E
- Receipt: artifacts/t02-root-current-async-receipt.json
- Receipt SHA-256: E633C37C8732E78004FF531375B8BC1F6D9B0BF061361AB4801631569AD64CB0
- Receipt root HEAD: 7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf
- Receipt git_apply_check: pending

This packet preserves candidate hunks only. Apply-check and root-current tests remain pending; no integration is claimed or authorized. Compare receipt preimage hashes with the then-current root before any future application.

## Repeat-runner

tools/repeat_t02_pytest.py allows only the delayed-dispatch cancellation selector, runs serially with fresh basetemp per attempt, writes logs and JSON receipt outside the repository, and caps the run at 50 attempts/900 seconds. Its unit selectors were run only under explicit narrow authorization; no 25-run reproduction was started by this edit.
