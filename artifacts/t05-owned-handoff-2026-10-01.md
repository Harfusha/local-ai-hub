# T05 owned handoff — 2026-10-01

## Candidate

Worktree: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub`
Base commit: `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`
Candidate snapshot patch: `artifacts/t05-owned-handoff-2026-10-01.patch`
Patch SHA-256: `AD8212E87F2539C423859A003B16721568B0327082574D8D8BCC4A66B604DF15`
`git apply --stat` succeeded: 16 paths, 3,136 insertions, 285 deletions. This is a candidate worktree snapshot, not an integration-ready patch: T20 reports root `git apply --check` fails across overlapping paths. Do not apply wholesale; integrate only owner-reviewed hunks.
Scoped cursor-callsite patch: `artifacts/t05-memory-cursor-callsite-handoff.patch`, SHA-256 `56622ACCBEB054D06A2E6806AC0C02192F24C824DD173559E55EA6BC5F780042`. Its root `git apply --check` succeeded.

## Owned paths

- `src/local_ai_hub/agent_events.py` — T05 guarded migration/version/backup/rollback safety envelope.
- `src/local_ai_hub/agent_memory.py` — memory identity, tenant/root scoping, sanitization, corruption handling, idempotency, canonical event stream, append callsites.
- `src/local_ai_hub/http_server.py`, `src/local_ai_hub/memory.py` — memory identity/delete transport and adapter.
- `tests/test_agent_memory.py`, `tests/test_agent_state_transport.py`, `tests/test_identity_contracts.py`.
- `tests/test_t05_agent_state_migrations.py`, `tests/test_t05_cache_state_isolation.py`, `tests/test_t05_cache_clear_durable_state.py`.
- `tests/test_agent_memory_http_identity.py`, `tests/test_memory_scope_delete.py`.

## Validation receipts

- `tests/test_t05_agent_state_migrations.py tests/test_t05_cache_clear_durable_state.py`: **23 passed in 18.22s** after fixture seeding used direct durable projection writes, keeping migration/cache-clear proof independent from T08 memory event writer.
- `tests/test_t05_cache_state_isolation.py`: **7 passed in 2.13s** after fixture seeding was decoupled from T08 memory event writer.
- T08 API overlay, three cursor selectors plus stale metadata/event regression: **4 passed in 0.45s**. T05 candidate source/test plus T08 `agent_events.py` and `sqlite_support.py` overlay. Receipt: `artifacts/t05-memory-cursor-integration-receipt-2026-10-01.md`.
- Same overlay, corrupt-row skip, private-field redaction/sensitive-write denial, correction lineage after reopen: **3 passed in 0.56s**.
- Post-callsite root-failure diagnosis: **4 candidate selectors passed in 1.03s** against current root T08 API overlay. Receipt: `artifacts/t05-root-event-and-scope-fix-receipt-2026-10-01.md`.
- Minimal root patch `artifacts/t05-root-event-and-scope-fix.patch` passed `git apply --check`; no root write.
- Root dry apply check for scoped cursor handoff patch passed earlier; no root writes.
- Fresh review follow-up: `source_root` exception now accepts only absolute path strings at top-level provenance; value and nested provenance fields remain private, and wrappers emptied by filtering are dropped. Rollback test proves record, event, and cursor exist inside transaction before injected failure. Current sanitizer patch SHA-256 `D39EF3B20DF990DFEBD1343425100BFBC1B64F8A75CA63887E72B672BE39FEA7`; rollback patch SHA-256 `A0997614AC342CC655775E0E617A9DEFC5CA20908D5CFB443DC03DF6C5052424`.

## Not yet verified

- Prior root focused batch reports **63/63 in 33.51s** across five cache/migration/memory/identity modules. Partial receipt only: root lacks three T05 corrupt-row/privacy/lineage selectors; do not treat batch as complete T05 acceptance. T20 applied minimal cursor, scope, and syntax-repair hunks; full candidate snapshot remains held.
- T08 create/resume memory adoption and T09 receipt acceptance remain outside T05 ownership.
- Two malformed earlier pytest invocations accidentally selected the full `test_agent_memory.py` module and were interrupted without a usable result. Do not count them.

## Ownership boundary

T05 owns migration safety envelope in `agent_events.py`. T08 owns only additive cursor DDL, legacy backfill, column validation, and public append/publication helpers. Insert T08 hunk inside existing guarded migration transaction; preserve T05 preflight, version/digest checks, verified backup, and rollback. T05 owns memory event callsites in `agent_memory.py`; T09 owns task/receipt orchestration. Do not copy T09 task files into this patch.

## Integration handoff — 2026-10-01

T08 added the missing `@contextmanager` decorator (T08 patch SHA prefix `312AABAF`); its root ordered-publication selector passes **1/1**. T20's first post-callsite root batch was **3 failed, 60 passed**: two tests queried legacy stale-event stream IDs; one exposed explicit WORKTREE lookup hidden by the no-root fallback. T20 applied the minimal scope/event patch and test syntax repair, preserving event-count assertions. Then root `python -B -m py_compile tests/test_agent_memory.py` passed, four focused selectors passed **4/4 in 1.65s**, and the five-module T05 cache/migration/memory/identity batch passed **63/63 in 33.51s**. T20 owns root selectors. T08 shared test slot release is pending. Full T05 bundle remains held; no T05 root write occurred.

## GLOBAL identity follow-up — 2026-10-01

T20 clarified current contract: preserve GLOBAL GET/list/context tenant filtering; shared GLOBAL fixture must be tenantless. Tenant-owned GLOBAL records stay tenant-isolated for GET/find. Explicit GLOBAL DELETE remains transport-tenant agnostic while root/repository guards apply. No production retrieval change requested.

T20 already corrected root `tests/test_agent_state_transport.py` fixture. T20 owns root HTTP/context selectors. T08 later released candidate slot; current T05 overlay batch is recorded below. The prior 5-pass candidate receipt and `t05-global-memory-identity-root-current.patch` came from an intermediate, reverted production policy; both are superseded. Current source preserves tenant filtering.

## Minimal root memory identity handoff — 2026-10-01

Root hunk artifact: `artifacts/t05-root-memory-identity-minimal.patch`, SHA-256 `0A4812A7A8218F3E8633BFDA46FD77914A3C3730983A285388247C8F1014136A`. It contains three hunks in `tests/test_agent_state_transport.py`: tenantless shared GLOBAL fixture, explicit GLOBAL GET/DELETE assertions, and scoped delete identity assertions. It excludes unrelated `app.memory.put` API changes. `git apply --cached --check --whitespace=error` passed against root index; `git apply --reverse --check --whitespace=error` confirmed those hunks already exist in root worktree.

T20 reports its exact root HTTP/context selectors passed **2/2**. Root fail-fast later reached **233 passed** and stopped on T08 crash-fixture receipt missing `command_id`; T08 owns that test-only repair. After the shared test slot was released, candidate-only memory selectors ran in an overlay using the current root T08 `agent_events.py` and `sqlite_support.py` API.

## Candidate three-selector command attempt — 2026-10-01

Exact command sent to `local_ai_command`: `$env:PYTHONPATH='src'; python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_memory.py::test_find_skips_corrupt_rows_without_aborting_scoped_read tests/test_agent_memory.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records tests/test_agent_memory.py::test_memory_correction_lineage_and_delete_survive_reopen` from the candidate worktree. Broker returned `request_not_sent=true`, `outcome_unknown=false`, `success=false`, request ID `req_d1b7ee853702`; this attempt produced no pytest output. After user-authorized fallback, the three selectors passed in the candidate overlay (**3 passed in 0.62s**). The strengthened privacy selector then passed alone (**1 passed in 0.22s**). Overlay supplied current root T08 `agent_events.py` and `sqlite_support.py`; direct candidate execution without that API overlay failed on missing `ordered_event_publication`, so these are candidate compatibility receipts, not root receipts. T20 later confirmed the strict root privacy selector passed **1/1**.

## T05 follow-up matrix — 2026-10-01

All runs used isolated temp overlay `C:\Users\Adam\AppData\Local\Temp\t05-acceptance-6a105f53b6584a449bfdf3271b11403c`, with candidate package/tests and current root T08 `agent_events.py`/`sqlite_support.py`; root remained unchanged by T05.

Bundle metadata selectors after the sanitizer fix:

```text
tests/test_agent_state_operations.py::test_selective_bundle_roundtrips_memory_metadata
tests/test_agent_state_operations.py::test_project_bundle_roundtrips_agent_state_memory_metadata
2 passed in 10.25s
```

The fixture used `sensitivity="sensitive"` while requiring the memory record to persist. It now uses allowed `normal` sensitivity; explicit sensitive-write denial remains covered by the privacy selector. Project import adds `provenance.source_root`; T05's broad `source` field filter had dropped that metadata key. The exact `source_root` allowlist exception restores lineage metadata while the privacy selector covers `source`, `source_text`, `raw`, prompts and secret payloads.

Scoped matrix command was one invocation: `PYTHONPATH=src python -B -m pytest -c pyproject.toml -q --tb=short -p no:cacheprovider`, followed by the 19 selectors below. Result: **19 passed, 2 failed in 12.84s**.

- `tests/test_agent_memory.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records`
- `tests/test_agent_memory.py::test_find_skips_corrupt_rows_without_aborting_scoped_read`
- `tests/test_agent_memory.py::test_find_for_context_excludes_stale_expired_and_corrupt_rows`
- `tests/test_agent_memory.py::test_memory_find_enforces_root_repository_and_tenant_identity`
- `tests/test_agent_memory.py::test_find_for_context_enforces_repository_tenant_and_task_identity`
- `tests/test_agent_memory.py::test_find_filters_global_and_repository_rows_by_tenant_and_root`
- `tests/test_agent_memory_http_identity.py::test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope`
- `tests/test_agent_memory.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope`
- `tests/test_agent_memory.py::test_scoped_memory_delete_requires_matching_tenant`
- `tests/test_agent_memory.py::test_memory_correction_lineage_and_delete_survive_reopen`
- `tests/test_t05_cache_state_isolation.py::test_scoped_memory_delete_preserves_all_relations_until_authorized`
- `tests/test_t05_cache_clear_durable_state.py::test_cache_namespace_clear_preserves_durable_agent_os_state`
- `tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases`
- `tests/test_t05_cache_state_isolation.py::test_sqlite_cache_recovers_corruption_after_first_initialization`
- `tests/test_t05_cache_state_isolation.py::test_process_crash_after_cache_rebuild_preserves_durable_agent_state`
- `tests/test_t05_cache_state_isolation.py::test_concurrent_derived_recovery_preserves_durable_agent_state`
- `tests/test_t05_agent_state_migrations.py::test_unversioned_current_schema_migrates_with_verified_backup_and_restart`
- `tests/test_t05_agent_state_migrations.py::test_historical_schema_version_migrates_and_preserves_legacy_event_versions` — failed only under full-file root T08 overlay; candidate migration rerun passes.
- `tests/test_t05_agent_state_migrations.py::test_concurrent_legacy_initializers_accept_completed_migration` — failed only under full-file root T08 overlay; candidate migration rerun passes.

The latter two are not candidate migration receipts: the full-file T08 overlay replaced candidate `AgentStateStore`, so it tested T08's current schema against T05 fixtures written for the older version-table schema. Follow-up isolated this: a fresh temp overlay preserved candidate T05 `agent_events.py` and migration code, adding only temporary T08 `ordered_event_publication`/`append_in_transaction` test shims. The same three candidate migration selectors then passed **3/3 in 3.39s**. No T05 migration code or expected behavior change is warranted by the earlier two failures. This remains candidate evidence, not a root integrated receipt.

T08-owned memory-use acceptance is absent from this worktree. T08 module `tests/test_agent_task_memory_adoption.py` selectors remain open: `test_create_uses_only_matching_root_and_tenant_without_saving_prompt_memory`, `test_create_and_resume_attach_only_scoped_negative_knowledge`, `test_resume_refreshes_memory_and_checkpoint_keeps_audit_bundle`, `test_stale_and_expired_memory_are_skipped_with_bounded_warnings`, and `test_volatile_memory_requires_checkpoint_source_check_and_bundle_survives_checkpoint`.

Patch SHA-256 receipts: sanitizer source hunk `t05-source-root-provenance-sanitizer.patch` = `D39EF3B20DF990DFEBD1343425100BFBC1B64F8A75CA63887E72B672BE39FEA7`; allowed-sensitivity bundle fixtures `t05-bundle-allowed-sensitivity-fixture.patch` = `AAC5AB41EFC872BD163D64AC3382097DE2505BE528D131B428368D55D4DD246B`; source-root/redaction boundary test `t05-source-root-redaction-boundary-test.patch` = `260601733C8B8BD9C049FAE0C27EE79096297A0E11FED436E0F28C5CC64255DB`; persisted-sensitive-write assertions `t05-root-memory-persisted-privacy-assertions.patch` = `85801174F5B904DC5029D631FCB80CD71854174617B9D8BEF0CFE515F8CF4980`. Earlier apply-check receipts apply to prior patch versions only. The old source-root boundary-test patch is superseded and fails candidate apply-check at `tests/test_agent_memory.py:123`. Current sanitizer patch fails root apply-check at `src/local_ai_hub/agent_memory.py:466`; rollback patch fails root apply-check at `tests/test_agent_memory.py:965`. Neither patch was applied. T20's latest root run reports T05 bundle/privacy selectors passed; the only later failure was T08 live-order. Acceptance remains open for integrated root migration proof, T08 memory-use selectors, trusted-local behavior, and fresh root receipts.

Original T05 acceptance remains open. Candidate snapshots and historic receipts do not replace fresh root proof for trusted-local boundaries, memory tenant/root/privacy/corruption/lineage, cache isolation, durable-state recovery, or migration/conversion safety. T08 owns task/resume adoption and cursor APIs; T09 owns receipt/completion gates. No root source implementation change for GLOBAL retrieval is proposed.

## Additional T05-owned acceptance — 2026-10-01

In the candidate-plus-T08-API overlay, memory event integration selectors passed **4/4 in 0.48s**:

- `tests/test_agent_memory.py::test_memory_write_failure_rolls_back_record_event_and_cursor`
- `tests/test_agent_memory.py::test_record_idempotency_is_atomic_under_concurrency`
- `tests/test_agent_memory.py::test_mark_stale_for_revision_preserves_metadata_and_emits_event`
- `tests/test_agent_memory.py::test_mark_stale_batch_rolls_back_and_repeats_idempotently`

The new failure-injection test proves event, cursor, and memory row exist inside caller transaction before raising, then verifies all three leave no durable row. Test-only patch `artifacts/t05-memory-write-rollback-test.patch` SHA-256 `A0997614AC342CC655775E0E617A9DEFC5CA20908D5CFB443DC03DF6C5052424`; candidate `git apply --check` passes, current root apply-check fails at `tests/test_agent_memory.py:965`. Patch remains unapplied. Earlier root apply-check used weaker test patch.

Safe memory/query selectors passed **3/3 in 5.17s**: `tests/test_agent_memory.py::test_model_conclusion_is_candidate_not_repository_memory`, `tests/test_agent_memory.py::test_evidence_memory_persists_revision_metadata_and_is_idempotent`, and `tests/test_agent_memory.py::test_memory_query_limit_is_hard_capped`.

Bounded/context safety selectors passed **5/5 in 7.10s**: `tests/test_agent_context.py::test_disabled_agent_state_returns_stateless_repo_context_warning`, `tests/test_agent_context.py::test_memory_diagnostics_are_repository_scoped`, `tests/test_agent_context.py::test_context_filters_before_candidate_limit_with_many_excluded_records`, `tests/test_agent_context.py::test_context_drops_unsafe_memory_store_fallback`, and `tests/test_agent_context.py::test_memory_diagnostics_aggregate_beyond_context_candidate_limit`.

These are candidate receipts only. T08 create/resume injection, checkpoint memory IDs/provenance and use-or-skip reason, bounded stale/expired warnings, and volatile-memory source checks remain T08-owned and have no receipt in this candidate run. T09 receipt/completion behavior remains T09-owned. T20 reports root T05 bundle/privacy selectors pass; T05 did not run root selectors.

## Current T08 API overlay — 2026-10-01

- T05 candidate suite used T08 `agent_events.py` and `sqlite_support.py` through a verified temporary package overlay; T05 `agent_memory.py` remained the tested source. **19 passed, 1 failed in 26.65s** across 20 selectors covering privacy, rollback, identity/scope, stale/corrupt reads, idempotency, bounded context fallback, HTTP identity, and bundle metadata. The only failure was `tests/test_memory_scope_delete.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_root_scope`; teardown raised `PytestUnraisableExceptionWarning` for two unclosed sqlite connections allocated at candidate `src/local_ai_hub/cache.py:520`. The direct T05 global-delete selector passed separately.
- Privacy, transaction rollback, and global-delete selectors passed **3/3 in 0.49s** on the same T08 API overlay.
- T08 adoption suite used T05 `agent_memory.py` with T08 task/event modules: **4 passed, 1 failed in 1.91s**. Only `test_create_uses_only_matching_root_and_tenant_without_saving_prompt_memory` failed because its helper writes a sensitive record and T05 correctly raises `ValueError: sensitive memory cannot be persisted`. Keep T05 rejection; T08 fixture needs a direct legacy-row seed or another non-sensitive test setup.
- Fingerprints: T05 `agent_memory.py` `EBDA97B0735FC7B65682AFCFE95AE3214789F06A70818EDD38823AF867C8334F`, `test_agent_memory.py` `6CB02CD0EF821F43AD1A30B12A891EC6A74D475B42BFDB06FA1ECF2684D8DAC2`; T08 overlay `agent_events.py` `B00AAF9A109B697CE7D3A8756EF3E88BD72772D2F36DEC30BF3ACDA76E6BABE3`, `sqlite_support.py` `7AC3F35553D57DF84E1C5A82AC2AE35095C8D07BD8EADA94B52F905B7449CA4B`.

- Follow-up: T08 adoption fixture now seeds the legacy sensitive row directly into durable tables, without the public writer or assertion changes. With T05 `agent_memory.py` overlaid on T08 task/event code, selectors passed **5/5 in 3.99s**. This supersedes the earlier 4/5 fixture-conflict result. T08 fixture SHA-256: `361F89CBE401B76EC2E50482169942A4DCC68A3F5412ABDFF7FA2F32270F36C0`.
- T07 setup-only fixture correction in this T05 candidate changes the memory put call to provide the source and named TTL; assertions unchanged. Targeted T07 and T05 memory receipts to follow.

- T07 fixture receipt: `tests/test_agent_state_transport.py` now calls `memory.put(root, key, value, source, ttl_seconds=...)`; no assertions changed. SHA-256 `83A61B134D31CA53677023342BCE165A1BD3461C43AAC71907DFDB45045096BE`. `test_coord_task_checkpoint_action_preserves_existing_memo_actions`: **1 passed in 9.36s**.
- Full T05 memory file ran from an isolated temp package copy with T08 `agent_events.py` and `sqlite_support.py` overlaid; import paths were printed and confirmed. `tests/test_agent_memory.py`: **37 passed in 23.67s**. Test SHA-256 `6CB02CD0EF821F43AD1A30B12A891EC6A74D475B42BFDB06FA1ECF2684D8DAC2`; tested T05 `agent_memory.py` SHA-256 `EBDA97B0735FC7B65682AFCFE95AE3214789F06A70818EDD38823AF867C8334F`. An earlier attempt accidentally imported T05 `AgentStateStore`; discard that failed receipt.

- Exact one-line T07 patch: `artifacts/t05-t07-fixture-one-line-2026-10-01.patch`, SHA-256 `99A7E6AE200CF7892C50E49EB91367195DC0324B3DF5719AEF064B95C2DB02B6`; `git apply --stat` and reverse apply-check pass.

## Fresh T05 acceptance receipts — 2026-10-01

- Root-current D1/D4 selectors: **6 passed in 0.88s**. Test files came from the T05 candidate; assertions verified both imported production modules came from root. Root HEAD was `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; root `agent_memory.py` and `agent_events.py` hashes stayed unchanged. Receipt `artifacts/handoff/t05-d1-d4-receipt-v4-20261001.json`, SHA-256 `F660530FEC1E2C83FF9223E1F4E5A2AA2900D03BBE3BBC6206EA6EB65F661DDF`.
- Candidate cache/migration/reopen selectors: **38 passed in 24.89s**, using only T05 test files; the existing 29-pass suite was not run. Receipt `artifacts/handoff/t05-d1-d4-receipt-v5-20261001.json`, SHA-256 `08A0786696AECA87E046D841182B02B5AF85BE9FEC1EF9C5636A14D66D417F2B`.
- Root migration/cache/restart proof and broader correction/delete/reopen/rebuild acceptance remain open. T20 owns root integration and plan updates; these receipts do not close full T05 acceptance.

- Root cache/migration selectors: **12 passed in 7.92s** using root modules. Covered derived-cache recovery, cache clear with durable Agent OS state, migration backup failure, verified-backup restart, unsupported version, and corrupt-state fail-closed. Existing 29-pass memory suite not run. Receipt `artifacts/handoff/t05-root-cache-migration-receipt-v6-20261001.json`, SHA-256 `FFD8907E90FF9D30D5CB15FBECCD7A000042FC038CE4E77526192E0181728D45`.
- Fresh root identity/privacy/correction-lineage receipt remains needed because prior 24-pass root receipt used `agent_memory.py` SHA `352C974FE41FF1065B2017DEDD34053794AB550958909A29E1BED3EF033E6FAC`; current root source SHA differs. T20 owns root test coordination and acceptance-plan updates.
- Root privacy boundary test handoff: `artifacts/t05-root-current-privacy-provenance-v1.patch`, SHA-256 `BDD30E02546487875F70683B3730B62707A40548889CABDC97FAFDEFF5BD5556`; current root apply-check passes. Adds raw/source payload and nested `source_root` redaction assertions while retaining top-level absolute repository provenance. Patch is test-only, unapplied, and unrun on root pending T20 slot and approval to refresh old selectors.
- T08 reported its focused run at **5 passed / 1 failed**: its candidate `MemoryStore.delete(record_id)` lacks T05 scope identity parameters. Source check confirms T05 candidate and root `delete()` require scope identity, while T08 candidate still has the one-argument signature. This is a stale T08 candidate integration seam; preserve T05 fail-closed guard. No T08 files changed.
- Static root/candidate privacy sanitizer parity: receipt `artifacts/handoff/t05-root-privacy-parity-receipt-v7-20261001.json`, SHA-256 `1C36DF90B9DD484EF342533BBC480326428BE6DE3738E65B663B4AD7E3B8368F`. It records matching AST hashes for the bounded privacy helpers/constants; this is static parity only and does not replace the pending fresh root privacy selector run. Test-only patch SHA remains `BDD30E02546487875F70683B3730B62707A40548889CABDC97FAFDEFF5BD5556`.
- After the T08 shared slot was observed idle, reran only the five listed T05 candidate memory/cache/migration selectors: **38 passed in 25.60s**. Receipt `artifacts/handoff/t05-d1-d4-receipt-v8-20261001.json`, SHA-256 `478EFAF5D79F04FE89B1ADE0F269CB09ED25D56F2D43567F9001F711DC255D29`. Production/test input SHA-256 values match v5. The existing 29-pass suite and root tests were not run.
- Root-current patch compatibility audit at root HEAD 98a9a1a7611af574caf20a88620c4aa3eb2e918a: five scoped delete/migration/HTTP identity/cache-worker handoff patches pass git apply --check; three older privacy/identity/context patches pass reverse-check as already applied. The delete-artifact production hunk also passes reverse-check as already present; root test file exists but differs from candidate hash. Receipt rtifacts/handoff/t05-root-patch-compatibility-receipt-v9-20261001.json, SHA-256 $h. Static compatibility only; no tests ran and this check did not edit root.
- T05 root test-surface map: candidate 	est_agent_memory_root_snapshot.py is byte-identical to root 	ests/test_agent_memory.py, so identity/privacy/delete/reopen cases can run as targeted root node selectors without running the full legacy suite. Root delete/cache/FTS test files exist but their fixtures/assertions differ from candidate versions. HTTP identity and extra scope-delete cases need an overlay or T20-approved root fixture. Static receipt rtifacts/handoff/t05-root-test-surface-receipt-v10-20261001.json, SHA-256 $h; no tests or root edits.

Prepared root-only node selectors (hold until T08/T20 release; do not invoke the complete legacy memory module): `tests/test_agent_memory.py::test_find_filters_global_and_repository_rows_by_tenant_and_root`, `::test_find_skips_corrupt_rows_without_aborting_scoped_read`, `::test_memory_write_redacts_private_fields_and_blocks_sensitive_records`, `::test_memory_correction_lineage_and_delete_survive_reopen`, `::test_legacy_unscoped_lookup_rejects_nonempty_task_and_session_context`, `::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope`, `::test_scoped_memory_delete_still_enforces_tenant`, `::test_legacy_memory_find_requires_explicit_root_or_identity`, `::test_memory_find_enforces_root_repository_and_tenant_identity`, `::test_memory_identity_indexes_exist_for_bounded_filtered_queries`, and `::test_memory_write_failure_rolls_back_record_event_and_cursor`. These are exact node names from the byte-identical root/candidate test source; they target root directly and exclude the full existing suite.
- Superseded HTTP identity test/patch v2 (`523C062...` / `369BC6...`) is obsolete. Current v3 includes persisted-storage/source-origin proof and the red/green results recorded in the following section.

## HTTP memory identity binding (2026-10-01)

- Receipt v1 below is historical and superseded: it incorrectly expected explicit GLOBAL DELETE to enforce transport tenant. T20's contract keeps GLOBAL DELETE tenant-agnostic while enforcing server-resolved root/repository identity.
- Candidate unit selector: **1 passed in 5.20s**. The candidate store lacks T08's `append_in_transaction`/`ordered_event_publication` API, so that run uses a narrow in-memory harness and is unit-only.
- Current-root hybrid overlay selector: **1 passed in 4.57s**. Candidate HTTP/memory modules ran with root `app.py`, `agent_events.py`, and `state_paths.py`; source-origin assertions passed, actual SQLite provenance was read back, and forged tenant/repository lookups and delete were denied.
- Root-current integration source patch: `artifacts/t05-root-current-http-memory-identity-v3.patch`; test-only patch: `artifacts/t05-root-current-http-memory-identity-test-v3.patch`. Both pass `git apply --check` against root HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`; source patch preimage hash is recorded in receipt v1. No root files were written.
- Receipt: `artifacts/handoff/t05-http-memory-identity-receipt-v1-20261001.json`.

## HTTP identity binding v4 — candidate selector refreshed; root overlay pending

- Candidate now binds GET and POST get/find to transport tenant and server-resolved root/coordination ID. POST record strips client root/repository ID/tenant, uses the resolved project identity (including a submitted nested provenance root), binds transport tenant, and records only the discarded field names. Explicit GLOBAL DELETE ignores transport tenant and binds root/repository identity.
- Root-current source patch `artifacts/t05-root-current-http-memory-identity-v4.patch` (SHA-256 `F19F62E761244B10F3383B4E08897051A0438482032271A3D76A8B11231CFFED`) and test patch `artifacts/t05-root-current-http-memory-identity-test-v6.patch` (SHA-256 `D45B296D3EA3AC9828109DECC3178FDA54BFCC50C9D6E4AB96F8CFFB599F9237`) both pass `git apply --check` at root preimage `http_server.py` SHA-256 `4B635B978EF556A69863507D9B7672604068997BE32C55CEFA1E1C1CCCC9C8BE`; root remains unmodified by T05.
- Current candidate selector passed **1/1 in 4.49s**, covering invalid-root denial, nested-root server resolution, client identity stripping, wrong-root GLOBAL DELETE denial, and transport-tenant-agnostic GLOBAL DELETE. Candidate uses `MemoryHarness`; this is unit evidence only. Receipt: `artifacts/handoff/t05-http-memory-identity-receipt-v2-20261001.json`.
- Root SQLite overlay selector remains pending T20/shared test-slot release. Re-run only this new selector with candidate HTTP/memory modules and root `app.py`/`agent_events.py`/`state_paths.py`; verify source origins and persisted provenance before issuing the integration receipt.

## Public SQLite HTTP identity regression — 2026-10-01

- Human clarified isolated temp SQLite/HTTP port-0 test does not use T08's shared test slot; root writes and gates remain T20-owned.
- Added `test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries` with real `LocalAIApp`, SQLite, loopback HTTP on port 0, and temporary Git repositories. It covers GET record/list, POST get/find, foreign tenant/root denial, ignored client tenant, exact-root legacy GLOBAL reads, provenance spoof stripping persisted as transport/server identity, wrong-root GLOBAL delete denial, and root-guarded tenant-agnostic GLOBAL delete.
- RED exposed candidate bug: tenant-owned GLOBAL row was hidden by `get()` before authorized GLOBAL delete. Added opt-in `tenant_agnostic_global` to `AgentMemoryStore.get/find`, rejects use outside GLOBAL scope, and passes it only from GLOBAL delete pre-read. GET/find retain tenant filtering.
- Candidate + current-root dependency overlay passed **1/1 in 7.94s**. Test asserts exact module origins: candidate `http_server.py`/`agent_memory.py`; root `app.py`, `agent_events.py`, `project_config.py`, `sqlite_support.py`, `state_paths.py`; root AgentStateStore exposes T08 append and ordered-publication APIs. Receipt `artifacts/handoff/t05-public-http-identity-receipt-v1-20261001.json`.
- Root-current memory patch `artifacts/t05-root-current-memory-global-delete-tenant-agnostic-v1.patch` SHA-256 `92D43E98D12B3DF172707274C3876E13C37462EF9837084956D5DA4E6F646CC5` and public-test patch `artifacts/t05-root-current-http-memory-identity-test-v7.patch` SHA-256 `6A95E75BF2EE9A7060269EE13ACDBB3562C8B836C7309DA8330909C091ADA756` pass current-root `git apply --check`; T05 did not edit root. T20 owns any root integration and gates.
- The previously approved existing 29-pass suite remains untouched. Full T05 acceptance, root integration, and remaining reopen/cache/migration receipts remain open.
