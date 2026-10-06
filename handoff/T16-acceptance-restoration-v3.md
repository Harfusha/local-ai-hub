# T16 acceptance restoration handoff v3

## Scope and ownership

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`

HEAD at inspection: `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.

T16 change in this continuation: `FencingLeaseStore.commit_guard` revalidates path and parent-attempt fencing tokens after protected writes and before SQLite COMMIT. The immediate SQLite transaction remains held across both checks and writes. Added regression coverage for both expiring tokens and for process death after `git apply` but before journal commit; restart recovery restores the preimage and requeues the work.

Ownership boundaries respected: T21-owned `src/local_ai_hub/project_config.py` untouched; T06-owned `src/local_ai_hub/commands.py` untouched; T20-owned root untouched. No commit or staging performed. Existing inherited dirty files remain mixed with other contributors' work; do not transfer or reset them as a unit.

## Evidence

RED, before production fix:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_commit_guard_revalidates_path_and_attempt_tokens_before_commit`

Result: `1 failed in 0.32s`; the test expected `LeaseLostError`, but commit guard did not revalidate expiry after the protected write.

GREEN, after fix and final test parameterization:

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py::test_commit_guard_revalidates_path_and_attempt_tokens_before_commit tests/test_work_fencing.py::test_commit_guard_rejects_expired_parent_attempt tests/test_work_fencing.py::test_expiry_reacquire_fences_stale_write_and_commit_without_side_effects tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal tests/test_work_handoff_acceptance.py::test_recovery_requeues_after_crash_between_journal_clear_and_state_update`

Result: `7 passed in 2.18s`.

Hub context/command broker was unavailable before request dispatch (`request_not_sent=true`); one bounded native pytest fallback was used. No repeated Hub request.

## T16 source integrity pins (SHA-256)

- `src/local_ai_hub/work_fencing.py`: `287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214`
- `tests/test_work_fencing.py`: `E7C82981577F48144E849B80EC473FBBA258B269EEEC05E84584228E04CA5A0D`
- `tests/test_work_handoff_acceptance.py`: `391503C600E03CDFD807D1F90A31734EC19CD5F94180E3F8CAD009AC833B4FCE`

These pin whole current files, including inherited content; they do not assert exclusive authorship of those files.

## Next owner: T20

Integrate only the T16-owned fencing recheck and regressions after reviewing inherited dirty state. Keep T21 `project_config.py`, T06 `commands.py`, and T20 root ownership separate. Carry the three SHA-256 pins above into the receiving audit. Existing T06 broker compatibility receipt remains from the prior handoff: 13 passed in 20.79s, log SHA-256 `4818FCB87FBF1CCBC1EB5A83D22A7E39438678F53EB3E8EBD450CDA453136B0A`.
