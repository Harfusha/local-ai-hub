# T16 static orchestration and ownership review — 2026-10-02

## Scope

- Candidate: C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub, HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11.
- Root: C:\Users\Adam\.local-ai-hub, HEAD 01df56605ccf484ebfe2808ac60d696c4e81dffc; working tree dirty, preserved.
- Static source review only. No tests/benchmarks. No root/T06/T15 edits. /api/context/pack untouched. T20 slot gates all later validation.

## Precise pins

| Path | Candidate SHA-256 | Root SHA-256 | Static status |
|---|---|---|---|
| src/local_ai_hub/work_orchestrator.py | 70C5084F02D4D1202C5375194324A6E6754C5623C4389DED19846CF4CE9B3AD5 | CBCCC1480BD9B9BF1BAB6EDCF41573E7390A61147F23A2946DE3D48BDDE78337 | 45/46 class method AST bodies match; only _rollback differs. |
| src/local_ai_hub/work_fencing.py | 287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214 | C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0 | FencingLeaseStore: 17/17 method AST bodies match. |
| src/local_ai_hub/leases.py | 173842B7359C8579868D72F448F52984A62E08B5FFEEE33A6EDC185481865793 | same | Byte-identical. |
| src/local_ai_hub/services.py | B1F1E117F49D566E067257E90868CD4134B736C1D3F49A783DC4EDE79BE9C97E | 525565A42B626A7ED2A66ADE57C6878D1802B430F2D1BD5A2818B7ADA68D3179 | Root has owner changes. Fence forwarding is present at root lines 6457–6472; do not overlay candidate file. |
| src/local_ai_hub/commands.py T06 | Candidate 5E3FD81C4AB55633A165237AE5C828CA2B73ACE353DA403DB67C98C65128E1D3 | Root 845348F2E362852561AE2EBB1B3F5458C8915E0134B1EC884F47356132B9FECB | T06 seam authority is root-owned. Candidate file does not expose root setter/fence symbols; never integrate candidate commands.py. |
| src/local_ai_hub/command_transactions.py T06 root | — | 247E49200044B4ACF2A1B261412F187C4688DE3CF0C9672AE582FD14EA1F029D | Read-only pin. |
| src/local_ai_hub/process_utils.py T06 root | — | 4D5A1AFBCB23BAB1FE4EEC6B9639743D17920DE93E7A822EF64840815998D4EB | Read-only pin. |
| tests/test_work_fencing.py | 1A2F8F34BF07F76ECEF0B303BFCAB0E0B8C96A1AE11D7477DBBBC4BB4C358807 | EEB23B457ED9C96786F4AF1763507CF8B97D5EA43B79AC187E4975D151CF3FDE | Root lacks junction alias selector. |
| tests/test_work_handoff_acceptance.py | 75F7B4AD282AC28257527FDEC1B6B3755F3DB471F52BC426C24B3F6336A66208 | 978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB | Root lacks partial-apply selector; TTL recovery selector exists. |
| tests/test_t16_cross_process_namespace_lease_recovery.py | 57D65635171198D378F74B34440B2892373C029FB1A9280AB51256D7DD046831 | D69F65E06443E76C8979A7F020C0DDD6F744FABFDCD84D5F79103C852D40FE44 | All selector names present in root; prior receipts only. |
| tests/test_t16_terminal_rollback_preflight.py | F7166F3BEB4D2964AB0C9F3D4EBDCE2A3E0B257D0D6A02CAD0690DE360F15771 | 77E556562217D68F0C3E248EFCD49CCB9E1063C26126AFB7888A9A8302378F28 | Root lacks junction-before-restore selector. |
| T16 broker fixture | A5472294E010E15D3C3FEA4CD19A82C3070B8279A858C603DD5026892FFE60CF | not present at same path | Prior isolated compatibility-overlay receipt only. |

Hashes pin current working files, not runtime acceptance.

## T06 seam review

Root WorkOrchestrator.__init__ passes its fencing store via set_fencing_lease_store; _execute_fenced emits writer_fence; root LocalAIServices.command forwards it as _work_attempt_fence; root T06 CommandBroker validates attempt identity/resource and wraps transaction commit under current-fence guard. Root commands.py owns these symbols. Candidate's T16-services-fence-forwarding.patch is stale: root already contains forwarding, old context does not apply. Keep all commands.py, command_transactions.py, process_utils.py integration with T06 owner.

Prior evidence: isolated compatibility fixture test_work_orchestrator_validation_reaches_real_broker_with_fence reported 1 passed in 2.26s; T06 handoff reported 13 passed in 20.79s. Neither is fresh root acceptance at pins above.

## Exact integration hunks

No T16 production source hunk is indicated by this comparison: fencing store, lease store, orchestrator methods except rollback, and root T06 seam are already present. Do not copy whole candidate services.py, work_orchestrator.py, or T06 files.

One root-current test-only hunk is ready: T16-partial-apply-failure-root-current-v1.patch, SHA-256 89C3C954C4D0CCF2EAAF09D2CA9F742AE20080D36FE4DC7E5BEA5BFFE8B7A081. Its recorded root test preimage is 978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB; prior read-only git apply --check --whitespace=error passed. Patch is not applied. It adds only partial two-file git apply rollback/journal regression.

Older root-current patches for cross-process atomic lease, commit race, crash-test placement, and junction coverage no longer apply to present root test context; do not use them blindly. Fence-forwarding patch also no longer applies because forwarding is already present. Refresh hunks only after T20 assigns integration/validation slot.

## Critical selector matrix

| Order | Shortest critical selector | Root state | Evidence/gate |
|---|---|---|---|
| 1 | tests/test_t16_cross_process_namespace_lease_recovery.py::test_two_process_linked_worktree_lease_expiry_reclaim_rejects_stale_commit | Present | Candidate prior subprocess receipt 1 passed in 9.76s; root run waits for T20. |
| 2 | tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens | Present | Candidate prior subprocess receipt 1 passed in 0.40s; root run waits for T20. |
| 3 | tests/test_work_handoff_acceptance.py::test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit | Present | Previously reported queued vs needs_agent RED has no stage exception; capture exact failing recovery stage before any fix. |
| 4 | tests/test_work_handoff_acceptance.py::test_process_crash_after_patch_write_recovers_from_persisted_journal | Present | Candidate prior focused receipt 1 passed in 1.04s; root run waits for T20. |
| 5 | tests/test_work_handoff_acceptance.py::test_partial_git_apply_failure_restores_all_preimages_and_clears_journal | Missing | Exact test-only patch above; run after T20 assigns slot. |
| 6 | tests/test_t16_terminal_rollback_preflight.py::test_rollback_rejects_junction_before_restoring_any_file | Missing | Windows junction evidence only; root-current test hunk needs refresh. |
| 7 | tests/test_work_fencing.py::test_rooted_scope_resolves_junction_alias_to_same_path | Missing | Junction alias is separate from symlink; root-current test hunk needs refresh. |
| 8 | handoff/T16-orchestration-broker-handoff-acceptance.py::test_work_orchestrator_validation_reaches_real_broker_with_fence | Fixture absent in root tree | Recreate owner-approved root-current test harness after slot; prior overlay receipt is not root proof. |
| 9 | T06 tests/test_command_transaction_snapshot.py::test_mutating_run_requires_authoritative_fencing_before_spawn | Present under T06 ownership | Run only in T20/T06-assigned serial batch. |
| 10 | T06 tests/test_command_transaction_snapshot.py::test_fenced_transaction_recovery_requires_current_work_attempt | Present under T06 ownership | Run only in T20/T06-assigned serial batch. |

Also missing: explicit process-death boundary after recovery restored all preimages but before journal clear becomes durable. Existing crash selectors cover worker write and journal-clear/state-update boundary, not this boundary. Add focused restart regression only under T16 ownership and after slot assignment.

Directory symlink remains unverified (WinError 1314); junction success is not a substitute.

## Current evidence boundary

Static source review only. T20 serial slot not released to this task. No tests/benchmarks or further validation now. Root owners decide patch application; no root/T06/T15 writes occurred here.