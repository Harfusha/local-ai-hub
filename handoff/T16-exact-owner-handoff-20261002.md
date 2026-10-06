# T16 exact owner handoff — 2026-10-02

## Trees and boundary

- T16 candidate: C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub, branch codex/t16-orchestration-recovery, HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11.
- Integration root: C:\Users\Adam\.local-ai-hub, HEAD 01df56605ccf484ebfe2808ac60d696c4e81dffc.
- Keep both dirty trees intact. No staging, commit, root write, T06/T15 edit, or /api/context/pack change.
- T16 scope here: orchestration attempts, fencing, lease namespace, recovery/rollback, isolated transaction handoff, HTTP lease routes. Exclude repository_test_impact.py and unrelated task paths.

## T16 source ownership reconciliation

| Concern | Current root evidence | Exact handoff |
|---|---|---|
| Fencing epochs and stale attempts | Candidate/root FencingLeaseStore method AST: 17/17 equal. Candidate work_fencing.py SHA 287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214; root C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0. | Already integrated semantically. No source hunk. |
| Shared lease namespace | leases.py byte-identical, SHA 173842B7359C8579868D72F448F52984A62E08B5FFEEE33A6EDC185481865793 in both trees. | Already integrated. No source hunk. |
| Work attempt/recovery flow | Candidate orchestrator 70C5084F02D4D1202C5375194324A6E6754C5623C4389DED19846CF4CE9B3AD5; root CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337. 45/46 class method AST bodies equal; only _rollback differs. | Root _rollback preflights all journal targets before writes. Candidate validates during restore-plan construction but still builds full plan before mutation. No demonstrated defect; keep root implementation. |
| HTTP lease identity | Candidate/root _lease_coordination_id AST hash both fed550fe6fd75a6b05dc040629eb9f049c5479bee083e266628b7ef7b08fe0a4. Root GET/POST lease routes derive coordination id server-side and pass it to store; client-provided coordination_id is ignored. | Semantically integrated. Do not overlay full http_server.py; it contains unrelated owner changes. |
| T06 isolated transaction handoff | Root orchestrator emits writer_fence; root services forwards as _work_attempt_fence; root T06 CommandBroker validates attempt identity/resource and guards transaction commit. | Root T06 files own this seam. Never copy candidate commands.py or replace root commands.py, command_transactions.py, process_utils.py. |
| Service-level fence forwarding | Root services.py SHA 525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179; candidate B1F1E117F49D566E067257E90868CD4134B736C1D3F49A783DC4EDE79BE9C97E. Root forwarding is present. | Candidate T16-services-fence-forwarding.patch is stale and unnecessary. Never copy candidate services.py wholesale. |

## Test fixture ownership reconciliation (static only)

- Candidate/root test selector test_http_lease_routes_resolve_namespace_and_isolate_linked_worktrees exists in both. Function AST differs only by root's additional recovery=RecoveryJournal(state_dir) fixture initialization. Root test pin E98FE68E1539AF8B9CC66940DC76562A59782856830437DFD53BE7B0770988BA; candidate D560EC58FD1250881D6D9241D6B2C6CE8A0E119F87B1C9C1CE809D97954363C2. Preserve root fixture; no test patch needed for this selector.
- Candidate/root critical epoch, TTL recovery, crash recovery, and namespace selectors exist by name. Their previously recorded receipts are candidate/prior evidence, not fresh root acceptance.
- Root still lacks these candidate selectors: test_partial_git_apply_failure_restores_all_preimages_and_clears_journal; test_rooted_scope_resolves_junction_alias_to_same_path; test_rollback_rejects_junction_before_restoring_any_file; direct real-broker fixture test_work_orchestrator_validation_reaches_real_broker_with_fence.
- Separate missing crash boundary: process death after all rollback preimages are restored but before journal clear is durable.
- Symbolic directory symlink remains unverified (Windows WinError 1314); junction evidence cannot replace it.

## Exact available hunk

- Optional root-current test-only partial-apply regression: T16-partial-apply-failure-root-current-v1.patch, SHA-256 89C3C954C4D0CCF2EAAF09D2CA9F742AE20080D36FE4DC7E5BEA5BFFE8B7A081.
- Root test preimage SHA-256 978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB.
- Previous read-only git apply --check succeeded; patch remains unapplied.
- Old cross-process, crash-placement, junction, and fence-forwarding patches have stale context or already-integrated targets. Do not apply them wholesale.

## Non-test acceptance

Static ownership and source reconciliation: PASS.
Fresh runtime/root acceptance: NOT RUN; T20 serial queue has not assigned T16 a slot.
Reported TTL recovery RED: unresolved cause; no stage exception captured. After slot assignment, run exact TTL selector first; on failure capture whether claim_batch, claim_attempt/acquire, rollback, checkpoint, or journal clear threw before changing source.
T06 broker acceptance, isolated transaction acceptance, Windows symlink acceptance: remain separate owner/platform gates.

## Next acceptance selectors after explicit T20 slot

1. tests/test_t16_cross_process_namespace_lease_recovery.py::test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit
2. tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens
3. tests/test_work_handoff_acceptance.py::test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit
4. tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal
5. tests/test_work_handoff_acceptance.py::test_partial_git_apply_failure_restores_all_preimages_and_clears_journal
6. tests/test_t16_http_lease_routes.py::test_http_lease_routes_resolve_namespace_and_isolate_linked_worktrees
7. T06-owned tests/test_command_transaction_snapshot.py::test_mutating_run_requires_authoritative_fencing_before_spawn
8. T06-owned tests/test_command_transaction_snapshot.py::test_fenced_transaction_recovery_requires_current_work_attempt

Do not repeat prior candidate selectors until assigned slot explicitly covers them. Do not run test/benchmark while T20 queue slot belongs to another task.
## Root-current combined regression patch refresh — 2026-10-02

- New exact hunk: handoff/T16-root-current-partial-apply-junction-v1.patch, SHA-256 714925C8AB22876D2226111B71D619A6A4FDDA9245339FFC0D6F09673EF01205; preimage manifest SHA-256 A33FB512EA47157855F2033B48A3A54FDAA3262B302863BCA9E86A0528242A64.
- Combines only three missing tests: partial apply restore/journal clear; junction alias canonicalization; junction rollback preflight. All three root preimage hashes matched at generation. Read-only git apply --check passed; patch remains unapplied, no tests.
- Root rollback raises ValueError during preflight. Junction regression hunk adapts candidate RuntimeError expectation to root ValueError while retaining message assertion.
- Do not combine with or apply alongside older individual partial-apply/junction patches.
- Detailed recovery/fencing stage plan and remaining gates: handoff/T16-recovery-fencing-regression-handoff-20261002.md.