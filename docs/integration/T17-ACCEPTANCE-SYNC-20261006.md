# Historical T17 acceptance reconciliation

Owned checkout: C:/Users/Adam/.codex/worktrees/t17-acceptance-2026-09-24.
Original tracked dirty checkpoint: 5b16828e, retained at
refs/checkpoints/t17-acceptance-sync-original-20261006.
Previously untracked Gemini audit spec committed as 67656de3.
Pinned master: 7cdf77e0. No stash, reset, deletion, or new feature work.

Manual conflict was limited to tests/test_transcription_contract.py.
Retain current process_utils.run_hidden mock boundary, timeout and cleanup
assertions, plus historical error/returncode/retryable assertions. Expectations
were not weakened to obtain a green run. Current deterministic format handling
already incorporates the historical source changes. Vision packet references
and returned findings use the previously normalized bounded_findings rather
than original unnormalized payloads. Both historical vision tests are retained.

Command: python -B -m pytest -q -p no:cacheprovider
tests/test_t17_auxiliary_formats.py tests/test_vision_contracts.py
tests/test_transcription_contract.py --tb=short --maxfail=4

Actual result: 96 passed, 3 failed in 7.21 seconds.
Remaining failures: parsed finding tuple test has no returned finding;
Whisper nonzero failure lacks returncode; Whisper timeout failure lacks
retryable. This preserves incomplete work, not verified task completion,
live Whisper/vision quality, or release acceptance. Runtime data stays outside
Git. Original checkpoints and historical stashes remain untouched.
