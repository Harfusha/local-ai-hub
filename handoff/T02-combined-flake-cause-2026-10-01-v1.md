# T02 combined-suite flake cause — 2026-10-01

## Result

Confirmed concrete cause for the repeated queue-cancel flake. Baseline `AsyncJobManager` can dispatch a delayed queued job from `tick()` before `submit()` registers its timer. Cancellation then observes `running` instead of `cancelled`. The already-present candidate patch persists a dispatch deadline and gates both timer dispatch and `tick()`. Exact regression selector is RED on HEAD implementation and GREEN on candidate implementation.

## Evidence

Historical combined-run receipt: `C:\Users\Adam\AppData\Local\Temp\codex-t02-flake-20260930T201729-b78b0be9.json` (SHA-256 `f602295b4b953034f4dadace78af297e448fd4aa8da28343bcb7c091b4d07fe2`; pinned HEAD `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`; only 3 records of requested 25). Attempts 2 and 3 fail `test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race` with `AssertionError: assert 'running' == 'cancelled'`. Attempt 1 captures the same assertion, live worker `async-job-fe63de95` after manager shutdown, scratch cleanup pending, and unclosed SQLite warnings. Its 16,000-character failure excerpt omits allocation frames; exact `sqlite3.Connection` owner remains unproven.

Regression test injects `manager.tick()` inside `_event`, after INSERT commit and before delayed timer registration. Baseline HEAD `async_jobs.py` has delay only in `threading.Timer`; its `tick()` selects queued jobs without a due-time predicate. Thus the injected tick dispatches immediately and cancellation sees `running`.

- RED: `head-async-jobs`, exit `1`, `5.106s`; exact failure `'running' != 'cancelled'`.
- GREEN: same selector, same test body, candidate `async_jobs.py`; exit `0`, `2.392s`.
- Candidate fix stores `dispatch_not_before` in row before `_event`; `_dispatch()` rechecks it on claim; `tick()` selects only due rows. Migration adds the field to existing schema. Candidate diff SHA-256 `0b2a899684ccabfe59ad8bf5360b4516d36cb83fc7cc108a07f565ff44fc7201`. No expectation changed.
- Additional minimal two-run comparison test passed: [handoff](T02-cancel-cleanup-reproducer-2026-10-01-v1/handoff.md). Both closes observed cancelled job, no live thread/process, SQLite write lock acquired, empty scratch.

## Scope boundary

No combined-suite rerun, 120-second harness rerun, 25x loop, or benchmark matrix. This proves the queue-dispatch race and candidate regression fix. It does not prove the full combined suite now passes. Historical SQLite warning likely shares the stranded-worker path, but exact connection ownership remains unverified.

No product source edits in this turn; candidate fix was already present as a dirty worktree change. Added prior T02 diagnostic test is `62d82421215849e538a302fc187c0343f8054949cedd78dfc1be94531dfee758`. Existing exact race test and expectations unchanged.

## Pinned roots

- Protected root `C:\Users\Adam\.local-ai-hub` HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Relevant tracked source hashes match prior snapshot.
- Candidate `C:\Users\Adam\.codex\worktrees\hub-audit-repairs\.local-ai-hub` HEAD `a7b0868ac964fd14e160001024e6e0ecaaf4e9db`.
- Candidate source hashes: `{"src/local_ai_hub/async_jobs.py": "6c245f4a52c4d1fd2a0d5ac50dfa6ce3e018b9cd2a400f27241690cc8bc97f0a", "tests/test_surface_benchmarks.py": "f4e0d299384b3b3c9443390ec1001ed6b6f38d5606c0b45d8d774ded816dcf00", "tests/test_t02_repeated_benchmark_cleanup.py": "62d82421215849e538a302fc187c0343f8054949cedd78dfc1be94531dfee758", "tools/benchmark_surfaces.py": "e93f2bbda52b62018d8f2ae4c4f148f0ccb7e24c37f3a3c3f1ebeeb0d7412457"}`.
- RED/GREEN command and logs: [queue-race evidence](T02-queue-cancel-race-2026-10-01-v1/receipt.json).
