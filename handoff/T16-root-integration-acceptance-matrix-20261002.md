# T16 root integration acceptance matrix — 2026-10-02

Pins and ownership reasoning: T16-recovery-fencing-root-review-v1.md.

| Slice | Root source/test pin | Critical selector | State |
|---|---|---|---|
| Epoch and stale writer fence | work_fencing.py C93C2221…0ECBDD0; cross-process test D69F65E0…D40FE44 | test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit; test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens | Source methods align; selectors present. Prior candidate receipts only. |
| Expired writer recovery | orchestrator CBCCC148…DE78337; handoff test 978B4E01…33BBEB | test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit | Present. Reported RED lacks captured exception stage. Run once after T20 slot; instrument stage if still red. |
| Crash after worker mutation | Same pins | test_process_crash_after_patch_write_recovers_from_persisted_journal | Present. Prior candidate receipt only. |
| Partial git apply rollback | Same pins | test_partial_git_apply_failure_restores_all_preimages_and_clears_journal | Missing. Scoped patch ready, unapplied. |
| Journal durability across recovery crash | Same pins | New selector needed: crash after preimages restored, before durable journal clear | Missing. |
| Junction rollback containment | terminal test 77E55656…2378F28 | test_rollback_rejects_junction_before_restoring_any_file | Missing. Existing old patch stale. |
| Junction lease canonicalization | fencing test EEB23B45…CF3FDE | test_rooted_scope_resolves_junction_alias_to_same_path | Missing. Existing old patch stale. |
| Symbolic directory symlink | Windows permission prevented creation | test_rooted_scope_resolves_symlink_alias_to_same_path | Unverified (WinError 1314). Keep separate from junction. |
| T16 to T06 real broker handoff | services 525565A4…68D3179; commands 845348F2…2B9FECB; transactions 247E4920…EA1F029D; process utility 4D5A1AFB…1598D4EB | test_work_orchestrator_validation_reaches_real_broker_with_fence plus T06 authoritative-fence and recovery selectors | Root seam present; integration fixture absent from root tree. Prior overlay receipt only. T06 owns broker paths. |
| Whole T16 batch | Candidate prior batch 79 passed, 1 skipped, 1 deselected | Acceptance command in checkpoint | Candidate-only, prior pin. Root acceptance pending T20. |

## Prepared handoff hunks

- Partial-apply rollback only: T16-partial-apply-failure-root-current-v1.patch, SHA-256 89C3C954C4D0CCF2EAAF09D2CA9F742AE20080D36FE4DC7E5BEA5BFFE8B7A081; root preimage 978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB; prior git apply --check --whitespace=error succeeded. Unapplied.
- No production hunks currently needed for T16 source in root. Old source/test patches fail current context or target already-integrated code; do not apply wholesale.

No tests/benchmarks or patch validation after T20 slot assignment. Root/T06/T15 files remain owner-controlled. /api/context/pack excluded.
## Current root-current hunk status — revision 2

The earlier single partial-apply hunk and stale junction patch references above are superseded by combined patch T16-root-current-partial-apply-junction-v1.patch.

- Combined patch SHA-256: 714925C8AB22876D2226111B71D619A6A4FDDA9245339FFC0D6F09673EF01205.
- Manifest SHA-256: A33FB512EA47157855F2033B48A3A54FDAA3262B302863BCA9E86A0528242A64.
- All three current root preimages matched; read-only git apply --check --whitespace=error passed (exit 0, empty output).
- Patch remains unapplied. No tests/benchmarks; T20 slot assignment still required.
- Root rollback junction assertion expects ValueError, matching root preflight behavior.