# T16 end-to-end acceptance checkpoint — 2026-10-02

## Scope and pinned trees

- Candidate: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Integration root: `C:\Users\Adam\.local-ai-hub`, HEAD `01df56605ccf484ebfe2808ac60d696c4e81dffc`.
- No root files changed in this continuation. Do not apply whole-file candidate diffs; T16 shares dirty files with T06/T20/T21.

## Preserved implementation and hashes

- Candidate and root `src/local_ai_hub/leases.py` match: SHA-256 `173842B7359C8579868D72F448F52984A62E08B5FFEEE33A6EDC185481865793`.
- Candidate `src/local_ai_hub/work_fencing.py`: `287DA1CDC5A8CA31EA96CE08D9D3D2EDC641F7BF7DC0F815BC3B2AECCED2F214`; root: `C93C22210A479DA74A8ACD19134BAE2BC80979BDDD55E9E5FA08A50042ECBDD0`.
- Relevant method bodies match across root/candidate: `FencingLeaseStore.claim_attempt`, `acquire`, `assert_current`, `commit_guard`; `ScopeLeaseStore._init_db`, `claim`, `release`; `WorkOrchestrator._recover`, `_ensure_workers`.
- Core namespace patch `handoff/T16-namespace-root-current-v5.patch`: SHA-256 `27242C3C4F9EA7113DC9E84C4179A6E937583175BF4ECEA64D605BC34A940459`.
- Cross-process commit-race patch `handoff/T16-root-current-cross-process-commit-race-v1.patch`: SHA-256 `CFCFF000F6FD1C3F1A3434B2B21BD8BB61AC5930A33D1B9AAB82C5BB027A4F66`.
- Lease migration patch already integrated: `t16_root_handoff_20261002.patch`, SHA-256 `EB8B1F906593A745557C23870AA73496EBA3A068B9D474D091F86B7563715405`. Its source preimage `362F4A...E694` is stale at root; current root already equals postimage. Do not reapply.
- Migration test candidate SHA-256 `AD76A7AB7220117D43F337192634978C3CAFCDF220841A176A043AE973D749C7`; root `AE9C916C2AEA3EDCE0192349E08778A005E096D7000B04E29AFDA2D4A1956D01`. Test content matches when CRLF differences are ignored.

## Acceptance receipts

- Cross-process lease/fencing candidate acceptance previously reported `7 passed`; root T20 reported `7 passed in 2.10s`. These are prior receipts, not a fresh run after the lease migration fix.
- After the migration fix, the two lease migration selectors passed in candidate: `2 passed in 0.24s`.
- Fresh full T16 candidate acceptance is pending. T02 owns the only test/benchmark slot. No test or benchmark ran during this continuation.

## Windows acceptance command prepared

Run in the candidate only after T02 explicitly releases the slot:

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_work_fencing.py tests/test_work_orchestrator.py tests/test_work_handoff_acceptance.py tests/test_t16_project_namespace_leases.py tests/test_t16_http_lease_routes.py tests/test_t16_cross_process_namespace_lease_recovery.py tests/test_t16_terminal_rollback_preflight.py tests/test_t16_lease_wait_namespace_isolation.py tests/test_t16_explicit_write_set_lifecycle.py -k 'not command_broker'
```

The symlink selector must remain enabled. A prior Windows attempt skipped it with `WinError 1314`; junction coverage is separate and is not a symlink substitute. WSL Ubuntu currently fails to start with `Wsl/Service/E_UNEXPECTED`, so there is no second-environment receipt.

## Next action

Wait for T02's explicit slot release. Run the prepared candidate command once, capture exact output and final candidate/root hashes, then update this checkpoint. Keep root writes and T06/T09 broker/cancel ownership separate.
## Recovery queued-state RED diagnostic — 2026-10-02

### Reported failure

The referenced RED receipt says `test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit` expected `queued` but observed `needs_agent` (plan line 1189). No test was run in this continuation; T02 owns the slot.

### Source diagnosis

- Candidate `_recover` starts with `recovered = journal is not None`. It writes `queued` only when recovery succeeds; any exception in fencing, rollback, checkpoint, or journal cleanup sets `recovered = False`, which writes `needs_agent`.
- Root and candidate hashes match for `_recover` (`CBD2860364A791BD2B637B912E9DAB17371AC8CD547FD8A3DFB785C0BBF1CEED`), `_record_recovery_checkpoint` (`286A0C6055EFC14DF326C0251D3A93B70DBAF204B29E54DC488A16560C589994`), journal load/persist helpers, and the reported test body (`423E4029D8394DCD1C42DA7CBB8202721F963867C7D9A48E971CE25F01E970B3`). Fencing claim/acquire/commit-guard methods also match.
- `_rollback` is the relevant source difference: candidate SHA-256 `A142FCDD90A562DA9E0DD2844CBEBC38D4381F8C878CC012B749A13FD3E492B2`; root `0CA8A38F7A7D97179DDF2331826748E531100A07424DD878DC09A261590E5E77`. Root preflights target paths and raises `ValueError` for unsafe paths; candidate validates each path during rollback and raises `RuntimeError`. For the test's single ordinary file, both implementations should validate the path, match the persisted postimage, restore the preimage, and succeed.
- Existing candidate receipt in `handoff/T16-acceptance-matrix-v1.md` includes this selector in a 7-selector run: `7 passed in 7.04s`. This is prior evidence, not a fresh rerun after the reported RED.

### Conclusion and regression plan

No unequivocal candidate lease/recovery defect is established, so no production code changed. The RED result has no captured exception from the recovery branch; `needs_agent` only shows that a caught exception marked recovery unsafe. Do not copy root `_rollback` wholesale or weaken path checks.

After T02 releases the slot:

1. Run this exact candidate selector and preserve full failure output if it fails:
   `python -B -m pytest -q -p no:cacheprovider --tb=long tests/test_work_handoff_acceptance.py::test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit`
2. If it fails, capture the exception at the narrow recovery stage (`claim_batch`, `claim_attempt`/`acquire`, `_rollback`, checkpoint, or journal clear) in a test-only wrapper. Add no duplicate regression unless the existing assertion cannot localize the failed stage.
3. Run the prepared full T16 candidate batch only after the serial slot is released. Keep T06 broker coverage excluded under its owner gate.

`git diff --check` and final file hashes belong in the post-slot receipt. Symlink acceptance remains separate: Windows `WinError 1314`; WSL startup `E_UNEXPECTED`.
### Read-only validation

- `git diff --check`: exit 0, empty output. No tests or benchmark ran; T02 still owns the serial slot.
## Root recovery/fencing review — 2026-10-02

- Read-only candidate/root review recorded in handoff/T16-recovery-fencing-root-review-v1.md.
- _recover, recovery checkpoint, journal helpers, and state-attempt guard AST bodies match current root; _rollback differs, but current RED lacks stage exception and does not justify a source change.
- Root-current test-only patch T16-partial-apply-failure-root-current-v1.patch SHA-256 89C3C954C4D0CCF2EAAF09D2CA9F742AE20080D36FE4DC7E5BEA5BFFE8B7A081 passed root git apply --check --whitespace=error (exit 0, empty output); not applied.
- Missing acceptance: process death after rollback restored all preimages but before durable journal clear. Symlink acceptance stays unverified (WinError 1314). TTL recovery selector remains post-slot diagnostic.
- No tests/benchmarks; no root/T06/T20 edits. T02 still owns slot.
## Static ownership pins and root acceptance matrix — 2026-10-02

- Detailed source/test pins, T06 seam boundary, scoped handoff patch and shortest selector order: handoff/T16-recovery-fencing-root-review-v1.md; concise gate matrix: handoff/T16-root-integration-acceptance-matrix-20261002.md.
- Current root has T16 fencing/recovery integration: 45/46 WorkOrchestrator method AST bodies match candidate; all 17 FencingLeaseStore method AST bodies match; leases.py is byte-identical. _rollback is sole orchestrator method difference.
- T06 root commands.py and related broker internals remain owner-controlled. Root source has setter and fence forwarding; T16-services-fence-forwarding.patch is stale. No T06/T15 source changed; /api/context/pack untouched.
- Root-current partial-apply regression patch remains sole prepared integration hunk; previously apply-check passed, unapplied. Old atomic-lease, commit-race, crash-placement and junction patches have stale root test context; no blind application.
- Root missing: partial apply recovery, junction canonicalization and rollback selectors, real-broker fixture, post-restore/pre-journal-clear crash selector. Symlink still unverified. TTL recovery selector present; reported RED needs stage-level exception.
- No tests/benchmarks or validation after T20 gate assignment. No root writes.
## T16 acceptance resume refresh — 2026-10-02

- Rechecked candidate HEAD 824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11 and root HEAD 01df56605ccf484ebfe2808ac60d696c4e81dffc. Prior source/test SHA pins remain unchanged.
- Root selector inventory unchanged: missing partial-apply test, junction alias test, rollback-before-restore junction test, and direct T16-to-T06 broker fixture. TTL recovery and cross-process epoch/fence selectors exist.
- Exact owned patch remains test-only partial-apply hunk T16-partial-apply-failure-root-current-v1.patch SHA-256 89C3C954C4D0CCF2EAAF09D2CA9F742AE20080D36FE4DC7E5BEA5BFFE8B7A081, root test preimage 978B4E01CFE36116838FB22451D409F7B72DC00836913D337C2DBFCAF233BBEB; unapplied.
- Root already carries orchestrator-to-services writer-fence forwarding and T06 broker seam. Do not apply candidate commands or broad services/orchestrator overlays. T06 retains commands.py, command_transactions.py, and process_utils.py.
- Isolated T16/T06 broker proof and T06 transaction selectors remain prior evidence only; fresh root acceptance blocked on T20 serial slot. No tests/benchmarks or edits to root, T06/T15, or /api/context/pack.
## Serial validation queue snapshot — 2026-10-02

- Read T20 thread 01a0d322-b3bd-7930-b552-14e9b7020fec at 2026-10-02 continuation: slot 11 is exclusively assigned to T11 and limited to local_ai_command; T05 slot 12, T03 slot 13, T08 no earlier than slot 14. T16 has no assigned slot.
- T11 preflight was reported 18/18 pins matching; T20 stopped attempted native pytest fallback. Slot 11 remains active. T16 ran nothing and waits for explicit T20 allocation.
## Exact T16 owner handoff — 2026-10-02

- Added handoff/T16-exact-owner-handoff-20261002.md with scoped source ownership, exact current candidate/root pins, no-source-hunk conclusion, existing optional test-only patch, root/candidate lease-route fixture delta, unverified gates, and shortest post-slot selector order.
- Static lease-route reconciliation: _lease_coordination_id AST matches candidate/root (fed550fe6fd75a6b05dc040629eb9f049c5479bee083e266628b7ef7b08fe0a4); route blocks use server-derived identity. Root HTTP test has one extra RecoveryJournal(state_dir) fixture field; preserve it.
- No tests or benchmarks run. T20 slot remains unassigned to T16. Root, T06/T15, and /api/context/pack untouched.
## T16 root-current partial-apply/junction handoff — 2026-10-02

- Generated test-only patch handoff/T16-root-current-partial-apply-junction-v1.patch, SHA-256 714925C8AB22876D2226111B71D619A6A4FDDA9245339FFC0D6F09673EF01205; manifest handoff/T16-root-current-partial-apply-junction-v1.json, SHA-256 CD750B84EF9A27DC9F13DE825C6F51DC033ACC46D95E5226B26A3E7FA5184A0D.
- Patch adds partial-apply rollback, junction alias, and junction rollback preflight selectors only. All three root preimage hashes matched during generation. Root rollback ValueError semantics captured in junction assertion.
- Patch unapplied. No apply-check/tests/benchmarks. Use combined patch only; do not duplicate older individual patches.
- Recovery/fencing exact stage plan: handoff/T16-recovery-fencing-regression-handoff-20261002.md. T20 slot still required before test acceptance.
## Root-current patch check receipt — 2026-10-02

- Current root still matches all three patch preimages in T16-root-current-partial-apply-junction-v1.json.
- Read-only git apply --check --whitespace=error passed for combined partial-apply/junction patch; exit 0, empty output. Patch remains unapplied.
- No tests/benchmarks. T20 remains active; no T16 slot assignment found.
## Current acceptance matrix revision pin — 2026-10-02

- Matrix revision 2 records the combined root-current partial-apply/junction patch and passed read-only apply-check: handoff/T16-root-integration-acceptance-matrix-20261002.md, SHA-256 E4A947D1914FD96F74D33D1956DEBD20858E18DA9C09285B444C3716247C867D.
- Exact stage plan and patch manifest are in T16-recovery-fencing-regression-handoff-20261002.md and T16-root-current-partial-apply-junction-v1.json.
- T20 remains active; no T16 test slot assignment found. No tests/benchmarks run.