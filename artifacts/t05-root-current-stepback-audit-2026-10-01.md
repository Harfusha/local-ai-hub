# T05 root-current stepback audit — 2026-10-01

## Scope and evidence boundary

- Root checkout: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.
- Root has live dirty changes in `agent_memory.py`, `agent_events.py`, `agent_tasks.py`, their tests, and untracked acceptance modules. This audit wrote nothing to root.
- Current root SHA-256: `agent_memory.py` `352C974FE41FF1065B2017DEDD34053794AB550958909A29E1BED3EF033E6FAC`; `agent_events.py` `7BBA75A0A335A1BEF0370F636D65F36477BF0638261723A1778E4DC06BB8B949`; `test_agent_memory.py` `F4F12E52C105D23E88A6F0F69A6D5AC2C23580BF9515E5DD1EA5C1EC6206E29C`; `test_agent_state_migrations.py` `E65BD621876ED30F647B1E68C6C6460FF9520457F45A2C48E1FA40C1C67386F2`; `test_t05_cache_state_isolation.py` `AEB9C347F94FF420B7995FBC18417375110D9C595F6E775CEE3C6F2309AD5F9C`.
- No tests run in this audit. Historical candidate/overlay pass counts, including 117, are not root receipts. Existing receipt hashes differ from current root files; treat them as stale for this dirty root snapshot.

## Confirmed T05 findings

### Scoped delete contract: T08 test caller is missing identity

`MemoryStore.delete()` requires an explicit scope and matching identity; `agent_memory.py:1809-1845` rejects an omitted scope and repository deletion needs the record `scope_id` plus provenance guards. Root `test_identity_contracts.py::test_memory_delete_requires_matching_scope_identity` asserts omitted scope returns false. The T08 selector `test_correction_stale_transition_and_delete_preserve_provenance_lineage` calls `memory.delete(correction.record_id)` at line 439, so its `True` expectation violates that contract. Proposed correction supplies `scope=REPOSITORY`, `scope_id=str(root)`, `root=str(root)`, and `tenant="tenant-a"`. This keeps GLOBAL behavior unchanged.

T20 separately reported this selector failing on root with `False`; source inspection identifies the same missing caller identity, not a reason to weaken the delete guard. The test-only fix is `artifacts/t05-root-current-scoped-delete-t08-test-fix.patch`; root `git apply --check` succeeds at a 3-line offset. No test was run here.

### GLOBAL versus scoped tenant behavior

Explicit GLOBAL delete intentionally ignores the transport tenant (`agent_memory.py:1847-1850,1875-1876`); GLOBAL is the stored scope and tenant labels are not authentication. Root selectors cover `test_global_memory_delete_ignores_transport_tenant_but_keeps_scope`, `test_scoped_memory_delete_still_enforces_tenant`, `test_memory_delete_requires_matching_scope_identity`, and HTTP `test_tenant_label_does_not_authenticate_http_request`. Do not change that rule.

### Confirmed delete-index cleanup gap

`MemoryStore.delete()` removes the record and entity relations (`agent_memory.py:1885-1895`) but does not remove `agent_memory_fts` or `agent_memory_embeddings`. `reap_expired()` explicitly removes both orphan stores (`agent_memory.py:1635-1648`), confirming delete cleanup is incomplete. The revised patch `artifacts/t05-root-current-delete-artifact-cleanup.patch` checks for an actually absent optional FTS table, then lets deletion errors propagate; it explicitly rolls back on failure. It adds `test_scoped_delete_purges_fts_and_embedding_artifacts` and `test_delete_fts_failure_rolls_back_record_and_embeddings`. This replaces the earlier unconditional OperationalError catch; that earlier form could report success with stale search data.

### Confirmed event-history/replay gap; T08 lifecycle boundary

Delete appends no `memory.deleted` event. The original `memory.recorded` event retains the value. On a repeated `record()` with the same idempotency key, `_record_event_and_save()` sees that event and, when its projection row is absent, reconstructs and saves it from the old payload (`agent_memory.py:728-750`). Thus deleting and replaying the original idempotency key restores the deleted record. Add a T08-owned tombstone/replay acceptance selector; do not alter event schema or retention from this T05 patch.

T08 relayed the root-current event API boundary: `AgentStateStore.append_in_transaction(con, event, strict_idempotency=False)` requires a caller-owned active transaction, writes the event and durable cursor together, and returns the stored event for a duplicate idempotency key. Enter `ordered_event_publication(con)` before `BEGIN`; publish only after commit. T08 owns the tombstone implementation using this seam. T05 cleanup remains projection-side and belongs in the same caller transaction; do not duplicate event schema, cursor, or retention logic. Relayed root locations: `agent_events.py:267` and `:383`.

T20 now reports the T08 tombstone patch is applied at root and its reopen/replay selector passed 1/1. At the fresh spot-check, root HEAD remained `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; root `agent_memory.py` SHA-256 is now `F6680A399A731E6CF40E79F19F4BC113B9EE72734F2FC48424D937292363CABE`. The delete path now appends/publishes `memory.deleted` inside its existing caller-owned transaction and already rolls back exceptions. The revised T05 hunk inserts artifact deletion after the projection-row delete and before relation cleanup; it has no exception catch.

Correction/status history is also incomplete: root `test_memory_correction_lineage_and_delete_survive_reopen` mutates the prior row through private `_save_record()` and checks the original event count, so the superseded transition is not represented by a new memory event. Preserve current scope/provenance guards; route lifecycle transitions through the T08 event API in the T08-owned integration.

## Durable state, migration, and cache loss

- Root durable store is `agent_state.sqlite3`; cache recovery targets the configured derived path. `SQLiteCache._recover()` quarantines that cache path and recreates it (`cache.py:420-452`). Root selectors already cover derived corruption/state preservation, first-initialization corruption, process crash after rebuild, concurrent recovery, and namespace clear. Missing root case: schema rebuild itself fails after quarantine, then retry; candidate selector is `test_cache_rebuild_failure_keeps_durable_state_intact_and_retries` in `tests/test_t05_cache_state_isolation.py` (candidate SHA `03FA37D07C2876598ADF390BCB482F822CAE808FBEB747601D26C736C616385F`). Not a root pass.
- Root migration uses backup before migration and a connection transaction (`agent_events.py:169-237`); `_verified_migration_backup()` verifies quick-check/schema and removes an owned partial backup on failure (`agent_events.py:239-265`). Existing root selectors: `test_current_unversioned_agent_state_migrates_with_verified_backup_and_restart`, `test_unsupported_future_schema_version_fails_closed_without_mutation`, `test_migration_backup_failure_prevents_schema_version_write`, and `test_corrupt_agent_state_fails_closed_without_replacing_bytes`.
- Missing root migration fault: inject failure after some migration DDL has run; verify rollback leaves version/schema/rows intact, verified backup remains, then retry succeeds. Candidate's migration module/hash `tests/test_t05_agent_state_migrations.py` `78E1B53F0CBC4F3B6E4889F60EA94F63893FBB8AB5E8F9C9093858E5352263B4` targets a different candidate migration API; do not transplant it as a root patch. Root-current selector should be `test_migration_ddl_failure_rolls_back_after_verified_backup_and_retry` in `tests/test_agent_state_migrations.py`.

## T08 memory adoption — seven core acceptance selectors

Root currently has dirty `agent_tasks.py` and untracked `tests/test_agent_task_memory_adoption.py`; the code wires `_task_memory_context()` into create/resume (`agent_tasks.py:247-317,738,1641`). At the last read, root test file SHA was `7709335CF1337D3F1A2017BD220311FA39B15554FFDBD4B69269116391593DA6`; root task source SHA was `9DA56C5C50B4E4E1171D358360314010832F32F1F3C22D93FD01CF5D4D24463D`. These are present, not fresh pass receipts.

Seven core selectors in that root module:

1. `test_create_uses_only_matching_root_and_tenant_without_saving_prompt_memory`
2. `test_create_and_resume_attach_only_scoped_negative_knowledge`
3. `test_resume_refreshes_memory_and_checkpoint_keeps_audit_bundle`
4. `test_corrupt_record_and_deadline_fail_open_with_warning`
5. `test_stale_and_expired_memory_are_skipped_with_bounded_warnings`
6. `test_correction_stale_transition_and_delete_preserve_provenance_lineage`
7. `test_volatile_memory_requires_checkpoint_source_check_and_bundle_survives_checkpoint`

The helper selectors `test_empty_lookup_is_silent_and_unavailable_lookup_fails_open` and `test_lookup_bundle_respects_item_and_token_caps` should remain in the same root batch. T08 owns adoption/lifecycle; T05's only required correction here is the missing explicit scoped-delete identity in selector 6, proposed in `artifacts/t05-root-current-scoped-delete-t08-test-fix.patch`.

## Candidate-only T05 evidence

- Migration fault candidates: `test_migration_backup_verification_failure_preserves_source_bytes_and_retries` and `test_migration_ddl_failure_rolls_back_after_backup_and_retry_succeeds` in candidate `tests/test_t05_agent_state_migrations.py`; no root receipt.
- Cache rebuild failure candidate: `test_cache_rebuild_failure_keeps_durable_state_intact_and_retries`; no root receipt.
- The prior 117-pass result belongs to an isolated candidate/overlay run. It is not evidence for current root hashes.

## Current handoff state

Prepared patches are candidate artifacts only: current delete cleanup SHA-256 `D1172532523A4D90D8FC7E27CBEE64C4D659F5990E504FD84DF4071C674F2C0D`; scoped T08 test fix SHA-256 `DA983C68832E4BCDBB2708449242E85CA315AE4C84E8E029EA03561F6A5375EC`; migration/cache fault tests SHA-256 `80333823725D719D7DC7282B4348CC0C7085F67AEDE2C9705401983B8F794902`. Each passes fresh root `git apply --check`; new test modules pass AST parsing. Exact added selectors: `test_scoped_delete_purges_fts_and_embedding_artifacts`, `test_delete_fts_failure_rolls_back_record_and_embeddings`, `test_migration_ddl_failure_rolls_back_after_verified_backup_and_retry`, and `test_cache_rebuild_failure_preserves_durable_state_and_retries`.

## T05 root slot receipt — 2026-10-01

T20 assigned one root command for the two delete selectors after its T08 tombstone integration. Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Exact command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t05_memory_delete_artifacts.py::test_scoped_delete_purges_fts_and_embedding_artifacts tests/test_t05_memory_delete_artifacts.py::test_delete_fts_failure_rolls_back_record_and_embeddings`. Result: **1 passed, 1 failed in 0.71s**.

- `test_scoped_delete_purges_fts_and_embedding_artifacts`: passed.
- `test_delete_fts_failure_rolls_back_record_and_embeddings`: failed in fixture setup before invoking `MemoryStore.delete`; `local_ai_hub.agent_memory` has no `sqlite3` attribute. It does not assess rollback behavior.
- Root test module SHA-256 at run: `77A976B4ECDBE0200649E1FD29144D6D883F67F3D98F9BDE0A3C939A97ECAF4D`. Root `agent_memory.py` SHA-256 at current review: `F6680A399A731E6CF40E79F19F4BC113B9EE72734F2FC48424D937292363CABE`.
- Candidate fixture fix patch SHA-256 `C5E743CA1C73E242D069BB260F14C84ED4E4F60200D77250047049027D31F1E0`; it patches `sqlite3.connect` directly. Root `git apply --check` passes; simulated patched fixture passes AST parsing.
- No retry run. T20 assigned one command and the slot is now free. Root files were not written by this audit; only test temporary files were created in pytest `tmp_path`.

## T05 resumed root-current acceptance — 2026-10-01

- Root HEAD remained `98a9a1a7611af574caf20a88620c4aa3eb2e918a`. Root source preimages: `src/local_ai_hub/agent_memory.py` `B3736D39B44722C9030CD9F47F58B58A5F86C1197921375310604EF31F79D8E7`; `agent_events.py` `7BBA75A0A335A1BEF0370F636D65F36477BF0638261723A1778E4DC06BB8B949`. Root test preimages copied byte-for-byte into the T05 worktree: `test_agent_memory.py` `F4F12E52C105D23E88A6F0F69A6D5AC2C23580BF9515E5DD1EA5C1EC6206E29C`; `test_identity_contracts.py` `C4FD7340F6AC649022908851CAB9DFD81536077EE0E33B6EC179FF4610CE4993`; `test_evidence_contract.py` `50794A86A3381A8EE0504DE466A7A69FB1C77AB0B305A3280CD1F308263A14B0`; migration test `E65BD621876ED30F647B1E68C6C6460FF9520457F45A2C48E1FA40C1C67386F2`; delete test `4F79E0C19498706AB351E8EC4F9CA617E95592EA9B351269DC87710B4FF22940`; cache test `AEB9C347F94FF420B7995FBC18417375110D9C595F6E775CEE3C6F2309AD5F9C`.
- Exact combined command: `python -B artifacts/t05-run-root-overlay-acceptance.py`. Result: **43 passed in 19.59s**, exit 0. Harness verifies all root import paths in-process and child cache workers; only `agent_memory.py` used a temporary overlay with the proposed scoped tenant guard. All fixtures use private temporary databases. No root files were written.
- Combined coverage: D1 scoped FTS/embedding purge and delete rollback (2); D4 FTS update failure rollback and optional-table behavior (2); root AgentMemory privacy, correction/lineage/delete, identity, and event rollback selectors (8); proposed SESSION tenant-delete guard (1); current root migration baseline and backup/DDL fault tests (6); cache recovery, rebuild-failure/retry, process-crash, and namespace-clear tests (7); root identity/shared-memory/evidence contract selectors (16); HTTP stale-identity delete race (1). T08 lifecycle/fencing source was not changed.
- Root gap confirmed: a scoped record carrying tenant provenance can currently be deleted without caller tenant. The exact root-current patch is `artifacts/t05-root-current-scoped-tenant-delete.patch`, SHA-256 `876CEF0B2CCA7E253BC1DDAFA2A5C16F6906A1BCBF3831807608344DD8DFD52D`; it adds the guard and regression. Root `git apply --check --whitespace=error` passed against source preimage above. The selector failed on unpatched root and passed with only this hunk overlaid.
- Test-only root-current patches: cache worker source proof `artifacts/t05-root-current-cache-worker-root-import.patch`, SHA-256 `C3966647EA97BD26DED761705BD8393756FC5DC098145EDE40979C718EBD6A84`; migration fault tests `artifacts/t05-root-current-migration-fault-tests.patch`, SHA-256 `E9D5C58A6173F8FEE2EE113B36AF4BCA2B9139E8DD8197E43A6A2D795A2AB8F4`; HTTP stale-identity test `artifacts/t05-root-current-http-memory-identity-test.patch`, SHA-256 `DEC2A091C4782ED474EFBB365D54FC4BB1642F677477C6C14A2671C6F8B52C05`. All pass root `git apply --check --whitespace=error`; root remains unchanged.
- Existing D1/D4 production patches are in current root: delete artifact cleanup SHA `D1172532523A4D90D8FC7E27CBEE64C4D659F5990E504FD84DF4071C674F2C0D`; fail-closed FTS update SHA `7F3C53BF1EF067ED00BBC2870642EE5851C904543410E9CD3CA9FADD090C6670`. Their selectors pass in the combined receipt.
- Out of T05 claim: one diagnostic broad run exercised stale candidate-only WorkspaceMemory APIs and the T06 concurrent derived-cache recovery race. Those selectors are excluded from the scoped combined receipt. The cross-process cache case failed once with a corrupt-derived-DB error and passed once; T06 owns that race. T08 lifecycle/fencing remains T08-owned.
