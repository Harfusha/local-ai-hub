# T16 revision 2 handoff

## Scope

- Candidate: `C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub`.
- Root: `C:\Users\Adam\.local-ai-hub`; this task made no root writes.
- T06 owns `commands.py` seam. Read-only source: `C:\Users\Adam\.codex\worktrees\t06-safe-commands\.local-ai-hub\src\local_ai_hub\commands.py`.
- T06 source SHA-256: `C8086EC310781755BEBCCBE5BBFE3C01BD0B5B6C652391A5680E9B8F1AAABCB8`.
- T06 API matches: `set_fencing_lease_store`, `run(..., _work_attempt_fence=...)`, attempt-aware recovery, guarded output import and journal writes.

## Root-current patches

- [Core patch](C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-r2-root-current-core.patch), SHA-256 `3C95A149A92D519B1E948190E1FA84E321FBE974F8CA2A78557EB920FF0F3C05`.
- [Service forwarding patch](C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-r2-root-current-services.patch), SHA-256 `716D18AA58309D807F4BAE84CFCA56D8E4C571D21DDB5374C841DF86CF191E95`.
- [Receipt test patch](C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-r2-root-current-receipts.patch), SHA-256 `9FAAECEFC9B529EDB2F05BB315D31548522DF756BCF65FC1EEA0671424E447B9`.
- Core/services/receipt patches passed `git apply --check --whitespace=error` before T20 integration advanced. Do not reapply them over T20's current dirty work.
- Orchestration patch is symbol-scoped. It keeps root rollback path/junction checks and adds hard-link refusal.
- Read-only comparison now shows current-root normalized `work_orchestrator.py` and `services.py` match the T16 transformed source. Root also has `work_fencing.py`, the T06 setter and `_work_attempt_fence` seam. Treat these as T20/T06-owned integration state.
- New isolated selector patch: [cross-process receipt patch](C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-cross-process-fence-receipt.patch), root test preimage SHA-256 `3CF82264563206B12AEA1CFFC0B78E12AE16D2FF650DE423730BE4A87A4A03D0`, patch SHA-256 `4AD248177721A43767838741305144304520392C0E44F7D4AC27017437439160`. Check-only `git apply --check --whitespace=error` passes; patch not applied.

## Touched files and owned hunks

- T16 core: adds `src/local_ai_hub/work_fencing.py` and `tests/test_work_fencing.py`; updates `src/local_ai_hub/work_orchestrator.py` imports, `_JournalEntry`, constructor, journal persistence/load/clear, recovery/retry, guarded state and receipt transitions, `_execute`/`_execute_fenced`, patch application, rollback transaction, rollback hard-link check, and close timer cleanup.
- T16 core acceptance tests: updates recovery/chained-rollback fixtures; adds `_fenced_journal_entry` and the recovery, stale-owner, hard-link, advisory-lease, and real-broker selectors below.
- T16 services: `src/local_ai_hub/services.py`, `LocalAIServices.command` run branch at current hunk `@@ -6080,6 +6080,10 @@` plus forwarded kwargs at `@@ -6091,6 +6095,7 @@`.
- T16 receipt tests: `tests/test_work_orchestrator.py`, updates rollback-failure fixture and adds verification-store, stale-receipt, and service-forwarding tests.
- T06 broker patch: `src/local_ai_hub/commands.py`, setter/payload validation, private transaction recovery attempt validation, guarded import/journal persistence/deletion, and `CommandBroker.run(..., _work_attempt_fence=...)`.
- T06 broker patch SHA-256: `AE14F18930F58F4A708AF0882BBAD3FD0D8FAE22C8679D3F870E2B86F32B95E8`.
- T06 expiry regression patch: `tests/test_command_rollback.py`; selector `test_expired_work_attempt_cannot_import_or_recover_transaction`.
- T06 expiry regression patch SHA-256: `69D8095D23603FFFF030320CC7639618CEFC017E27DCFB47F68174D9DBE10707`.

## Ordered application dependency

1. Apply T16 core first. It adds `work_fencing.py`, required by the broker seam.
2. Apply T06 `T06-root-current-broker-fence.patch` (`commands.py`).
3. Apply T06 `T06-root-current-expired-attempt-test.patch` (`test_command_rollback.py`).
4. Apply T16 services patch; it forwards `writer_fence` into the now-supported broker parameter.
5. Apply T16 receipt test patch. It depends on T16 core only.
6. Run integrated selectors only after T20 review permits root validation. No root write or test occurred in this handoff update.

## Regression selectors

- `test_stale_attempt_cannot_complete_or_clear_successor_journal`.
- `test_rollback_refuses_hardlinked_postimage`.
- `test_recovery_defers_live_attempt_without_journal`.
- `test_invalid_patch_releases_advisory_lease`.
- `test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit`.
- `test_stale_verification_receipt_cannot_complete_work_order`.
- `test_local_service_forwards_receipt_opt_out_and_keeps_work_id`.
- `test_real_command_broker_accepts_forwarded_work_attempt_fence` is present but unrun; T06 seam is not integrated into candidate `commands.py`.
- `test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens` proves two subprocesses share the candidate SQLite DB and persist the successor receipt.
- T06 selectors: `test_expired_work_attempt_cannot_import_or_recover_transaction`, `test_expired_transaction_lease_cannot_overwrite_newer_declared_path`, `test_transaction_recovery_completes_outputs_from_persisted_journal`, and `test_transaction_recovery_preserves_foreign_change_and_keeps_journal`.
- Combined root validation should also run T16 `test_real_command_broker_accepts_forwarded_work_attempt_fence`, `test_recovery_reacquires_fence_after_writer_ttl_and_rejects_stale_commit`, and `test_rollback_refuses_hardlinked_postimage`.

## Validation

- AST parse passed for six transformed/candidate Python files.
- Isolated candidate selectors: `13 passed, 1 skipped` in 2.92s. Skip: Windows denied directory symlink creation (`WinError 1314`).
- Cross-process selector command: `py -m pytest -q --tb=short tests/test_work_fencing.py::test_subprocess_attempt_supersession_rejects_stale_commit_with_monotonic_tokens`; result `1 passed` in 0.35s. It uses two subprocesses, one temp DB, increasing attempt/path tokens, rejects stale attempt and commit, preserves successor output, and writes `state/successor-receipt.json`.
- First run exposed a `retry_index`/attempt-token name collision; fixed by renaming loop counter. Stale-receipt test stub now forwards `attempt=`.
- Real broker selector remains for T20's root slot. No root test/write, broad suite, GPU benchmark, or shared-port test ran after review gate.
- T20 review gate is active. Cross-process patch awaits that review; do not apply it yet.

## Completion state

T16 S1-S5 source is in T20's current integration state. Cross-process receipt patch is ready for review. End-to-end completion remains open until T20 root selectors, including real broker expiry/recovery and hard-link rollback, pass.

## Lease-namespace consumer follow-up

- Proposal: [T16-project-namespace-consumer-proposal.md](C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-project-namespace-consumer-proposal.md).
- Candidate implementation changes `project_config.py`, `leases.py`, `work_fencing.py`, and `work_orchestrator.py`; fake lease adapters accept internally derived ID.
- Candidate acceptance batch passed `63 passed, 1 skipped, 1 deselected` in 41.12s. Skip is Windows symlink privilege (`WinError 1314`); deselected selector is T06 real broker adapter.
- Real subprocess namespace selector passed `1 passed` in 1.92s. Each child resolved `ProjectContext.coordination_id`; successor committed from linked worktree; stale child commit was rejected.
- Root-current broker overlay test passed `1 passed` in 1.44s. It loaded root `commands.py` by asserted module origin and committed a real write under `commit_guard`; expired attempt then failed closed. `commands.py` remains untouched.
- `git diff --check` passed.
- No root writes or tests after T20 gate. Candidate results do not prove root integration. Do not replace current root files with stale T16 patches; surgical patch is available below and remains unapplied until gate release.

## Root-current namespace patch

- Patch: [T16-namespace-root-current.patch](C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-namespace-root-current.patch).
- Manifest: [T16-namespace-root-current-patch.md](C:\Users\Adam\.codex\worktrees\t16-orchestration-recovery\.local-ai-hub\handoff\T16-namespace-root-current-patch.md). Includes predecessor hashes, symbol ownership, and acceptance receipts.
- Root-current `git apply --check` passed. Patch includes lease namespace bridge, fencing scope migration, orchestration context wiring, linked-worktree/process tests, and actual broker commit/stale-rejection test. It leaves `commands.py` unchanged.
- Do not apply until T20 gate releases and hashes still match.
