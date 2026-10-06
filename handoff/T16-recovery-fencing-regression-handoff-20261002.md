# T16 recovery/fencing regression handoff — 2026-10-02

## Boundaries

- Candidate HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11; root HEAD 01df56605ccf484ebfe2808ac60d696c4e81dffc.
- T16 orchestration/lease tests only. No source change, root write, T06/T15 edit, or /api/context/pack change.
- No tests/benchmarks. Read-only git apply --check passed; T20 owns serial test slot.

## Root-current regression patch

Patch: handoff/T16-root-current-partial-apply-junction-v1.patch  
SHA-256: 714925C8AB22876D2226111B71D619A6A4FDDA9245339FFC0D6F09673EF01205  
Manifest: handoff/T16-root-current-partial-apply-junction-v1.json  
Manifest SHA-256: A33FB512EA47157855F2033B48A3A54FDAA3262B302863BCA9E86A0528242A64

Three test-only additions. Patch generator verified each current root preimage SHA before writing and records root postimage hashes. Patch not applied.

| Root path | Root preimage SHA-256 | Selector | Root adaptation |
|---|---|---|---|
| tests/test_work_handoff_acceptance.py | 978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB | test_partial_git_apply_failure_restores_all_preimages_and_clears_journal | None |
| tests/test_work_fencing.py | EEB23B457ED9C96786F4AF1763507CF8B97D5EA43B79AC187E4975D151CF3FDE | test_rooted_scope_resolves_junction_alias_to_same_path | None |
| tests/test_t16_terminal_rollback_preflight.py | 77E556562217D68F0C3E248EFCD49CCB9E1063C26126AFB7888A9A8302378F28 | test_rollback_rejects_junction_before_restoring_any_file | Root preflight raises ValueError; candidate expected RuntimeError. Hunk expects ValueError with same symlink/junction message. |

Do not apply this combined patch with older partial-apply or junction patches; selectors would duplicate.

## Recovery and fencing evidence

- Candidate/root WorkOrchestrator method AST: 45/46 equal; only _rollback differs. Root preflights every journal target before restore writes. Keep root version; no demonstrated production defect.
- Candidate/root FencingLeaseStore methods: 17/17 equal. ScopeLeaseStore leases.py byte-identical.
- HTTP lease namespace resolver and route snippets derive coordination identity from server ProjectContext. Root test adds RecoveryJournal fixture; preserve current root test body.
- Root T06 seam already receives writer_fence through LocalAIServices and validates it in CommandBroker before/within isolated transaction commit. T06 owns broker and transaction source.

## Remaining regression plan (run only after T20 assigns T16 slot)

1. Epoch/reclaim: tests/test_t16_cross_process_namespace_lease_recovery.py::test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit.
2. Direct stale holder: tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens.
3. Reported RED: tests/test_work_handoff_acceptance.py::test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit. If red, preserve full exception and identify failing stage: claim_batch; claim_attempt/acquire; commit_guard; rollback; recovery checkpoint; journal clear. Change no source before stage evidence.
4. Crash recovery: tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal.
5. Apply the three-test patch selectors above, serially.
6. Journal durability boundary still lacks a regression: crash after rollback restored all preimages but before durable journal clear; design a focused restart test under T16 ownership.
7. Broker acceptance remains T06-owned and needs root-current T16 orchestrator-to-broker fixture; prior overlay receipt is not root proof.
8. Directory symlink remains unverified on Windows (WinError 1314); junction selectors do not replace it.

## State

Non-test source/ownership handoff: complete.
Root-current regression patch: three preimages match; read-only git apply --check passed; unapplied.
Fresh acceptance: pending explicit T20 slot assignment to T16.
## Latest preimage/apply-check receipt — 2026-10-02

- Rechecked all three root preimage hashes against the patch manifest; all MATCH.
- Ran git -C C:\Users\Adam\.local-ai-hub apply --check --whitespace=error C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-root-current-partial-apply-junction-v1.patch: exit 0, empty output.
- Check only; patch remains unapplied and root unchanged. No tests/benchmarks.
- T20 task remains active; no explicit T16 slot assignment found.