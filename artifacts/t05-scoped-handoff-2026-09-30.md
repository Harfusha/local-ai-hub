# T05 scoped handoff — 2026-09-30

## Status

Formal T05 goal already exists and remains `BLOCKED`; no duplicate goal created. No root files changed by this audit. T06 cross-process invalidation and T08 recovery remain excluded.

## Latest source review — 2026-09-30

- Current AgentMemory candidate adds optional `tenant` to `MemoryStore.delete`. Scoped deletion checks record, scope, scope ID, and normalized tenant provenance in one `BEGIN IMMEDIATE` transaction. Missing tenant can delete only tenantless legacy rows. GLOBAL deletion ignores transport tenant. Relation cleanup runs only after matching row deletion.
- `MemoryStore.find` uses the same tenant normalization and JSON provenance expression. `/api/agent-state/memory` verifies identity before delete and rejects non-GLOBAL deletion, so its existing call does not need to pass tenant for GLOBAL rows.
- Review found no static mismatch in the new delete predicate. Runtime regression selectors remain unverified because no shared test slot was assigned. Earlier suite receipts predate this candidate.
- HTTP dirty preimage remains the integration blocker: recorded SHA256 `d7bec2b689c8256260b320b40a46940bd01ba05ddcaaa5805f45c278dce510df` is absent from available artifacts. Current raw file hashes differ from that preimage; do not claim whole-file provenance or integrate the mixed patch.

## Owner-only audit and prepared cross-process regressions — 2026-09-30

### Identity and shared-memory semantics

- `WorkspaceMemoryStore` is deliberately workspace-shared. Its `memos` primary key is `(workspace, memo_key)`, not tenant. Writes replace the shared value and expose tenant as a label. Existing identity-contract tests assert this behavior. Tenant label is not authentication or private tenant isolation.
- `WorkspaceMemoryStore.put` and `delete` use `BEGIN IMMEDIATE`; expected-version check, generation update, upsert/delete occur in one transaction. New subprocess regression has two writers race at expected version 1; contract is one version-2 winner and one conflict.
- `AgentMemoryStore.delete` filters exact record ID, scope, scope ID, and tenant provenance for scoped rows in one transaction. GLOBAL ignores transport tenant. Relation cleanup happens only after exact record deletion. HTTP route verifies root/repository identity first and rejects non-GLOBAL deletion because API token lacks server-verified project/worktree context.
- Compatibility: `tenant` is an optional keyword. Omission still permits legacy tenantless scoped rows; tenantful scoped rows require matching tenant. GLOBAL deletes retain root/repository verification at read boundary.

### Durable recovery, process races, and redaction

- Durable `agent_state.sqlite3` stays physically separate from disposable `cache.sqlite3` and `code-index.sqlite3`. Existing parameterized recovery test corrupts each derived DB, reopens task/event/memory/receipt/lease stores, then confirms durable DB has no corruption quarantine.
- `SQLiteCache` recovery lock is process-local; `CodeIndex` lock is instance-local. Concurrent recovery can repeat quarantine/rebuild and lose derived cache entries, which are disposable. Static paths show neither recovery routine targets `agent_state.sqlite3`. New subprocess regression synchronizes two workers before cache/code-index recovery, requires both to exit cleanly and final derived SQLite integrity, then verifies durable task and memory. It does not require derived cache entries to survive the race.
- Debug trace request capture recursively redacts sensitive-key values, caps encoded payload at 8 KiB, caps each list at 100 items, and omits unsupported/binary payloads. Memory values and workspace memo metadata remain intentionally readable to trusted-local callers; trace redaction is not tenant authorization.
- T08 `agent_events.py` migration/recovery ownership remains excluded. No source file changed in this audit turn.

### Exact pending selectors

- `tests/test_agent_memory.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope`
- `tests/test_agent_memory.py::test_scoped_memory_delete_requires_matching_tenant`
- `tests/test_agent_memory_http_identity.py::test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope`
- `tests/test_identity_contracts.py::test_workspace_memos_report_shared_scope_and_isolate_repositories`
- `tests/test_identity_contracts.py::test_workspace_memo_expected_version_rejects_stale_overwrite`
- `tests/test_identity_contracts.py::test_workspace_memo_expected_version_serializes_across_processes`
- `tests/test_identity_contracts.py::test_memory_delete_requires_matching_scope_identity`
- `tests/test_identity_contracts.py::test_privileged_lease_tenant_label_cannot_spoof_owner`
- `tests/test_identity_contracts.py::test_mixed_memory_identity_context_is_rejected`
- `tests/test_identity_contracts.py::test_artifact_lookup_is_tenant_scoped_and_evidence_ids_are_repository_scoped`
- `tests/test_memory_scope_delete.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_root_scope`
- `tests/test_memory_scope_delete.py::test_tenant_memory_delete_requires_tenant_and_matches_provenance`
- `tests/test_memory_scope_delete.py::test_memory_delete_rejects_unknown_scope`
- `tests/test_agent_memory.py::test_record_idempotency_is_atomic_under_concurrency` (thread-level)
- `tests/test_agent_memory.py::test_conflicting_high_confidence_insert_is_atomic_under_concurrency` (thread-level)
- `tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases[cache]`
- `tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases[code-index]`
- `tests/test_t05_cache_state_isolation.py::test_sqlite_cache_recovers_corruption_after_first_initialization`
- `tests/test_t05_cache_state_isolation.py::test_process_crash_after_cache_rebuild_preserves_durable_agent_state`
- `tests/test_t05_cache_state_isolation.py::test_concurrent_derived_recovery_preserves_durable_agent_state[cache]`
- `tests/test_t05_cache_state_isolation.py::test_concurrent_derived_recovery_preserves_durable_agent_state[code-index]`
- `tests/test_t05_cache_clear_durable_state.py::test_cache_namespace_clear_preserves_durable_agent_os_state`
- `tests/test_debug_trace_request_summary.py::DebugTraceRequestSummaryTests::test_command_list_row_has_redacted_summary_only`
- `tests/test_debug_trace_request_summary.py::DebugTraceRequestSummaryTests::test_http_trace_capture_redacts_nested_sensitive_values_and_omits_large_or_binary_data`

Shared pytest slot remains queued behind T07/T08; none of these selectors ran after current edits. Modified test files and embedded subprocess scripts passed AST parsing; `git diff --check` returned clean aside from existing LF/CRLF notices.

### Current raw SHA256 values

- `src/local_ai_hub/agent_memory.py`: `6c4e935b46b01f32a2e5c88223a2287dddd169b411a87d5094882cd27af898df`
- `src/local_ai_hub/http_server.py`: `684f0362c667289d2b3e08bcf193c0c5a70d80aeb9735808f83ba876d0d05925`
- `src/local_ai_hub/memory.py`: `58211a3a02ea090591c1cac67efb61c8111f5d40a06a17be5a2afc618652e517`
- `src/local_ai_hub/cache.py`: `e69ac756c8df9fc21d5e2a5ef57d3670be307be50285d6c12f935ccd693c29cf`
- `src/local_ai_hub/code_index.py`: `d6cd501589a8d264648fdc4aff68d8db8a603e7cfbd8585c8902feaaf541f376`
- `tests/test_agent_memory.py`: `7393cae5206916eb6d3b527f3c7bf226e4690156bd36abb1c9f9cc40b894c202`
- `tests/test_agent_memory_http_identity.py`: `f25293991676c89b0a7740ed32c40c888d5b949c76244f5385cd5516885fa9b5`
- `tests/test_identity_contracts.py`: `73ec7eec1c12b0f20516f064fba2ec4fb3fec97bc344227daa9dbc6c31cc2eb8`
- `tests/test_memory_scope_delete.py`: `5e84a8116a5fb98c8e10488d63dc6e74993f86050aa4b3310dce24801d3ccb69`
- `tests/test_memory_http_validation.py`: `a65a1454adfb7d7149853a1548d3a1489936125221286a14c4016453dd170f3c`
- `tests/test_debug_trace_request_summary.py`: `bef31d9bf74633432a810f8af45d5199c0f04dcbeeae601a2b4b4cbd67d5add9`
- `tests/test_t05_cache_state_isolation.py`: `f6b92a67287b3ec07cfd2b758a1414426ba4b15c4457e04eb65837db5814f333`
- `tests/test_t05_cache_clear_durable_state.py`: `7178ba62817a5abc21e5173f109e1bcd6645ff7362c47eacf488d116a71880db`

## Assigned worktree and root

- Assigned worktree: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub`, HEAD `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`.
- Root: `C:\Users\Adam\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Blob values below are Git blob OIDs. Root current files are dirty; never overwrite them with these patches without a coordinated merge.

## Core AgentMemory handoff

- Main scoped patch: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub\artifacts\t05-agent-memory-core.patch`, SHA256 `be595039667d74674ad55313aaab36c2f866c4f6f864d7ec77201cf68a8b0940`.
- Paths: `src/local_ai_hub/agent_memory.py`; `tests/test_agent_memory.py`.
- Worktree base/current blobs: AgentMemory `4e6fb2fdbf829c188ebc73081c88e85b90482f6f` / `6bcd7c1d4563b67db19de13958e33408786eed32`; test `c96309b1a4b57eec3f360faa51493e90234f87ec` / `1d770266eaff3a18806e33e41470e036791c320a`.
- Root base/current blobs: AgentMemory `c53e05b814e46bbac63b2f65aa87fab5d29fbca0` / `68ff0946fd5aa3b30ab698eb90c5f5970dce8101`; test `c96309b1a4b57eec3f360faa51493e90234f87ec` / `6652947b436e90b35ab471cab8bc5a16274bb9be`.
- Root dirty AgentMemory already has equivalent GLOBAL tenant-filter condition. Root dirty test has same-named but narrower delete test and different idempotency assertions. Do not apply patch wholesale.
- Isolated command `git apply --check --verbose <absolute core patch>` returned exit 1 at AgentMemory context (`if tenant:` is already changed in root). Test-only patch `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub\artifacts\t05-agent-memory-core-tests.patch` returned exit 1: its global test hunk could insert a duplicate name; later event assertion hunk expects obsolete stream IDs. Manual merge required.
- Single-source patch: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub\artifacts\t05-agent-memory-source.patch`, SHA256 `a2af0896affd9fe1faf4bfc027d487b96a9ddf92a4f298a9f3f3b37a5c0052ef`. Isolated `git apply --reverse --check --verbose <source patch>` against assigned current file exit 0; forward check against root current file exit 1 because root already has the condition. Earlier assigned-worktree check `git apply --reverse --check artifacts/t05-agent-memory-core.patch` also passed. Unit/identity suite receipts are in acceptance evidence.

## Cache-state and clear tests

- Cache-state patch: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub\artifacts\t05-cache-state-isolation\t05-cache-state-isolation-root.patch`, SHA256 `c042a77ad123e12dedbf898fd2bf7ce256eafce37ca86aaac6cd34e3b6e91f69`.
- Root and assigned current `tests/test_t05_cache_state_isolation.py` blob OID both `defa1197cbe35237ea97d3cf3cf01573f0d0681c`. Isolated `git apply --check --verbose <cache patch>` returned exit 1 because current root content no longer matches patch context; do not overwrite.
- Cache-clear test root/worktree blob OID both `ba84613d4b785e2e796f7cded8b9ac6f4d78bd8a`; raw SHA256 both `7178ba62817a5abc21e5173f109e1bcd6645ff7362c47eacf488d116a71880db`. Fresh assigned selector: `$env:PYTHONPATH='src'; python -m pytest -q --tb=short -p no:cacheprovider tests/test_t05_cache_clear_durable_state.py::test_cache_namespace_clear_preserves_durable_agent_os_state` => `1 passed in 3.26s`. Root run separately reported `1 passed in 0.79s`.

## HTTP identity split and blocker

- Unattributed HTTP-only hunk: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub\artifacts\t05-agent-memory-global-delete\http-server-unattributed.patch`, SHA256 `734a575c54245aa2ab801f628977a8c63611f0b5290def07b5776226da01b614`.
- Original scoped candidate: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub\artifacts\t05-agent-memory-global-delete\t05-agent-memory-global-delete.patch`, SHA256 `95470136256ea5b93f0e793d288f53f31afe238165f84189c9f562f3c255223e`.
- `http_server.py` worktree base/current blobs: `b99476b285b82ba6c4f4b9f88a80926802cbad93` / `334e57d04067fc19617f3d2c8b7c3b39c88c497e`. Root base/current blobs: `2e3b23bd3ebe8f2ebeba44fe0d70b59888f31ed2` / `d23f3e9882f66b7d482973942469cea1d02464d2`.
- Recorded dirty preimage SHA256 `d7bec2b689c8256260b320b40a46940bd01ba05ddcaaa5805f45c278dce510df` was not found. Reconstructed candidate `09d9bf15a36a1447e13acb8c264b349ca16c8affe013f71b3f0d68b468952696` differs. Current root and worktree raw SHA256 are `d311b7c34f694864e0d4b4b316db656bdd643b5b36de58642f4e9c3411840cf0` and `684f0362c667289d2b3e08bcf193c0c5a70d80aeb9735808f83ba876d0d05925`.
- Isolated `git apply --check --verbose <HTTP-only patch>` returned exit 1: candidate expects old `record = APP.agent_memory.get(record_id_val)` line, absent from current root dirty file. Do not apply or claim provenance.
- Endpoint-test-only patch: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub\artifacts\t05-agent-memory-global-delete\http-identity-test.patch`, SHA256 `85ea00be99f182762569fdd53502f95e9ba18cf79cf9e628e20e0d499f5e40cf`. Isolated `git apply --check --verbose <HTTP identity test patch>` returned exit 0 because root lacks that test. It depends on current dirty HTTP behavior and does not resolve source provenance.
- Existing `tests/test_agent_memory_http_identity.py:102-117` sends tenant `codex`, denies wrong root without deleting, then deletes under matching root/repository. Recorded selector: `1 passed in 7.85s`.

## Acceptance and open items

- T05 in-scope suite: `117 passed, 1 skipped`; skip is Windows symlink privilege. Cache/reopen/corruption/crash module: `5 passed`; migration module: `22 passed`. Shared identity/trust suite: `29 passed, 1 skipped, 1 deselected`. Detailed exact commands are in `t05-acceptance-evidence-2026-09-30.md`.
- Combined T05 plus inherited lifecycle run had `138 passed, 1 skipped, 1 failed`; failure was T08-owned migration concurrency preflight. Isolated rerun passed `1 passed`.
- `git diff --check` clean after test correction.
- Open: exact provenance of mixed `http_server.py` dirty preimage; safe attribution/integration of that hunk. Root has dirty equivalent-looking behavior, but no verified base. No root writes or integration performed.


## Additional current blob IDs and isolated checks

- `tests/test_agent_memory_http_identity.py`: root absent; assigned base absent, current blob `ec6355542e7af09c6735103c4721678ee97892e8`.
- `tests/test_t05_cache_state_isolation.py`: root base absent/current `defa1197cbe35237ea97d3cf3cf01573f0d0681c`; assigned base `2ad8e7a89af372f1eeb1209340a8398553e8b21c`/current `defa1197cbe35237ea97d3cf3cf01573f0d0681c`.
- `tests/test_t05_cache_clear_durable_state.py`: root and assigned base absent/current `ba84613d4b785e2e796f7cded8b9ac6f4d78bd8a`.
- Exact isolated command form: `git apply --check --verbose <absolute patch path>`, run with a temporary directory containing copies of only required current-root files. Core patch exit 1 at already-changed `if tenant:` context; HTTP-only patch exit 1 at missing old direct-get context; core-test-only patch exit 1 after hunk 2 and stale event assertion; cache-state patch exit 1 at drifted context; HTTP identity test-only patch exit 0 because target file is absent.
- Isolated reverse check of source-only patch against assigned current source exited 0. Forward check against current root source exited 1 because root already contains this condition.

## Handoff boundary

The scoped artifacts are ready for integrator review. Apply test-only HTTP identity patch only with awareness it exercises root's currently dirty HTTP implementation. Do not apply the unattributed HTTP source patch. Core source behavior is already present in root's dirty file, but clean root commit integration requires manual merge of the overlapping root test and other dirty changes. Acceptance evidence is complete for owned independent criteria; HTTP source attribution remains open.


## Physical SQLite separation and T05/T08 ownership

- T05-owned `tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases` is parameterized over `cache.sqlite3` and `code-index.sqlite3`. It asserts each derived path differs from `agent_state.sqlite3`, overwrites derived DB bytes with corruption, opens the recovery path, requires SQLite `quick_check=ok` and a `.corrupt-*` quarantine, then reopens durable stores.
- It verifies task contract, event, memory, receipt row, lease, durable DB existence, and no `agent_state.sqlite3.corrupt-*` file. Latest scoped suite above includes both parameter cases and passed `117 passed, 1 skipped`.
- `tests/test_t05_agent_state_migrations.py::_assert_state_survives` additionally verifies task, event, snapshot, memory, and verification completion through migration/reopen. Migration module receipt is `22 passed`; combined run exposed one schedule-sensitive T08 concurrency-preflight failure, and its isolated selector passed `1 passed`.
- Ownership boundary: T05 adds recovery-isolation tests only. `agent_events.py` migration/schema-preflight implementation remains inherited T08 ownership; no T08 source or data-preservation requirement was weakened or edited.


## Scoped-delete ownership audit (read-only; no tests run)

- T05 `AgentMemoryStore.delete` at `src/local_ai_hub/agent_memory.py:1688` is not `delete(record_id)` alone. It requires explicit `scope`; non-GLOBAL also requires `scope_id`; SQL deletes on `record_id + scope + scope_id`. It has no tenant argument, so caller must first verify full identity.
- `/api/agent-state/memory` performs `APP.agent_memory.get` with scope/root/repository/tenant context at `http_server.py:2579`, denies non-GLOBAL delete at `:2594`, then deletes by verified GLOBAL scope at `:2603`. Existing `tests/test_agent_memory_http_identity.py` sends transport tenant `codex`, rejects wrong root, then confirms matching GLOBAL deletion. This is T05 behavior; no new test needed.
- `/api/memory/delete` is separate `WorkspaceMemoryStore` path: `http_server.py:3693` passes root, key, transport tenant, and scope to `APP.memory.delete`; implementation is `memory.py:332`. It requires tenant for tenant scope and filters by tenant; GLOBAL clears tenant while retaining root/workspace scope.
- Existing focused tests are `tests/test_memory_scope_delete.py::test_tenant_memory_delete_requires_tenant_and_matches_provenance` and `::test_global_memory_delete_ignores_transport_tenant_but_keeps_root_scope`. Both were included in the last T05 suite (`117 passed, 1 skipped`). T18 report of an unscoped record-ID delete does not match this worktree's current call graph.
- No test executed in this audit because shared test slot was not assigned. No `agent_memory.py`, `memory.py`, or HTTP source changed. No T05-owned deletion bug confirmed beyond unresolved HTTP preimage provenance.


## Pending scoped-delete regression (awaiting test slot)

- Added focused assertions in tests/test_agent_memory.py: existing GLOBAL delete now supplies tenant=codex; new test_scoped_memory_delete_requires_matching_tenant checks missing/mismatched tenant cannot delete, correct tenant can delete, then record is absent. Test file SHA256 7393cae5206916eb6d3b527f3c7bf226e4690156bd36abb1c9f9cc40b894c202.
- TDD red run is pending shared test-slot assignment. No test command ran and no production source changed. Current AgentMemoryStore.delete signature lacks tenant, so candidate tests are expected to fail at call boundary until slot permits RED confirmation and minimal implementation.
- After assignment: run both focused selectors; confirm failures are missing tenant behavior, implement atomic tenant predicate in AgentMemory deletion, rerun selectors, then rerun full T05 suite. Do not touch http_server.py, memory.py, root, or T08 source.
- git diff --check remains clean. Goal stays open/blocked for HTTP preimage provenance and pending owned deletion validation.


## Deferred tenant-delete implementation
- Current assigned test file SHA256: 7393cae5206916eb6d3b527f3c7bf226e4690156bd36abb1c9f9cc40b894c202.
- Test additions are working-copy candidates only: test_global_memory_delete_ignores_transport_tenant_but_keeps_scope now passes tenant=codex into GLOBAL delete; test_scoped_memory_delete_requires_matching_tenant covers absent tenant, wrong tenant, matching tenant, and post-delete absence.
- Production signature at agent_memory.py:1688 currently accepts only record_id, scope, scope_id. Static source therefore predicts these tenant-keyword tests fail with TypeError; no execution occurred, per unassigned shared test-slot constraint. No production code change made.
- When slot is assigned, run both focused selectors RED, implement tenant-filtered SQL atomically while GLOBAL ignores tenant, then run focused selectors and full T05 acceptance suite. Preserve T08 and HTTP ownership.



## Current AgentMemory tenant-delete candidate (test slot pending)
- Production candidate now in assigned worktree only: AgentMemory delete accepts optional tenant. Inside same BEGIN IMMEDIATE transaction, scoped delete matches record_id, scope, scope_id, and tenant provenance; absent tenant matches only tenantless rows. GLOBAL delete deliberately omits tenant predicate. Relations are removed only after matching record is deleted.
- Core patch SHA256: 26e718bf696f40defddfacebd99895b9524443f93c0b91502dfa2f7d65892e40. Source-only patch: 8ee7ad3308060d75f98f3341dbfecceb5a417d5aee7f5083b62067fa1b3dd4e8. Test-only patch: 6bb6edc8bf0bbd35f62fa282004a7a54b0b1d58c0c653861c625a581d43749ae.
- Worktree base/current blobs: agent_memory.py 4e6fb2fdbf829c188ebc73081c88e85b90482f6f / 3b3ff8cbdda0a613a1ff731b6cf84ff62b4ea06f; test_agent_memory.py c96309b1a4b57eec3f360faa51493e90234f87ec / cc8bf28f79423fba6c0ae62ac6b1a8132f3eaac1.
- Isolated root apply checks: source-only forward check exit 1 because root already contains the GLOBAL get change; test-only forward check exit 1 because root test hunk overlaps an existing same-named regression and later expects obsolete idempotency assertions. Assigned-worktree reverse checks for source and tests both exit 0. No root writes.
- Static checks: git diff --check clean; AST parse of both changed Python files passed.
- Focused selectors are pending shared slot: tests/test_agent_memory.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope; tests/test_agent_memory.py::test_scoped_memory_delete_requires_matching_tenant. No tests ran after candidate edits. Prior 117 passed, 1 skipped suite predates these edits and is not current validation.
- Next: run focused selectors RED/GREEN in assigned slot, fix failures, rerun focused selectors and complete T05 suite. Preserve HTTP provenance blocker, root, and T08 ownership.

## Continuation update 2026-09-30
- Scoped HTTP delete TOCTOU is now closed for supplied root/repository identity: `MemoryStore.delete` repeats both provenance predicates inside its `BEGIN IMMEDIATE` transaction, and the route forwards those request predicates. Regression in `tests/test_agent_memory_http_identity.py` simulates provenance reassignment after GET and expects DELETE 404 while the reidentified record remains.
- Debug trace redaction now normalizes camelCase and catches sensitive key segments (for example `client_secret`, `clientSecret`, `X-LocalAI-Token`, `x-api-key`); corresponding regression is in `tests/test_debug_trace_request_summary.py`.
- Static evidence only: AST parse passed for `agent_memory.py`, `http_server.py`, `test_agent_memory_http_identity.py`, and `test_debug_trace_request_summary.py`; `git diff --check` clean (Git emitted line-ending conversion warnings). No pytest run; shared slot remains unassigned.
- Current raw SHA256: `agent_memory.py` B79D06DFC2A0FD4085C5825C8C923FBE187762B250E8741F6040F6CBCD28E341; `http_server.py` 49EBEF7CC1AFB2C523AE064F1CA601E9937E3EF397C4E85239A92B4E63E6C420; `test_agent_memory_http_identity.py` 4E037BDAABE47F3386009D43669CD861ECC9A37F6522CBDFE9C837F1402B544F; `test_debug_trace_request_summary.py` 792114950F68F6A8C002ED53AA5E24A8D4D4890580F00D57F1AFFEE3F57D10D5.
- HTTP whole-file preimage remains unverified; preserve mixed inherited/T05 hunks and do not transplant the full file. T08 `agent_events.py` and agent-2 `/api/context/pack` ownership remain untouched.

## Hunk ownership and T20 test handoff
- Own in this continuation: `http_server.py:425` sensitive-key boundary regex; `:687-688` camelCase normalization; only DELETE argument forwarding at `:2604-2609` (`root`, `repository_id`) inside the pre-existing T05 identity handler. `agent_memory.py` adds matching atomic predicates to `MemoryStore.delete`; the HTTP regression reassigns provenance between GET and DELETE.
- Inherited before this continuation: the rest of the `/api/agent-state/memory` identity/delete handler at `http_server.py:2552-2603`; legacy `/api/memory/delete` scope validation at `:1061-1064` and legacy route forwarding at `:3698-3702`; all other dirty-file hunks. The full dirty preimage SHA256 `d7bec2b689c8256260b320b40a46940bd01ba05ddcaaa5805f45c278dce510df` is still unavailable, so this is working-tree/history attribution, not a verified whole-file reconstruction. Preserve every unlisted hunk.
- Immediate owned-hunk selectors for T20: `tests/test_agent_memory_http_identity.py::test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope` (includes GET/DELETE identity race); `tests/test_debug_trace_request_summary.py::DebugTraceRequestSummaryTests::test_http_trace_capture_redacts_nested_sensitive_values_and_omits_large_or_binary_data`.
- Focused T05 identity/trust selectors: `tests/test_agent_memory.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope`; `tests/test_agent_memory.py::test_scoped_memory_delete_requires_matching_tenant`; `tests/test_identity_contracts.py::test_workspace_memos_report_shared_scope_and_isolate_repositories`; `tests/test_identity_contracts.py::test_workspace_memo_expected_version_rejects_stale_overwrite`; `tests/test_identity_contracts.py::test_workspace_memo_expected_version_serializes_across_processes`; `tests/test_identity_contracts.py::test_memory_delete_requires_matching_scope_identity`; `tests/test_identity_contracts.py::test_privileged_lease_tenant_label_cannot_spoof_owner`; `tests/test_identity_contracts.py::test_mixed_memory_identity_context_is_rejected`; `tests/test_identity_contracts.py::test_artifact_lookup_is_tenant_scoped_and_evidence_ids_are_repository_scoped`; `tests/test_memory_scope_delete.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_root_scope`; `tests/test_memory_scope_delete.py::test_tenant_memory_delete_requires_tenant_and_matches_provenance`; `tests/test_memory_scope_delete.py::test_memory_delete_rejects_unknown_scope`.
- Focused T05 cache/state selectors: `tests/test_t05_cache_clear_durable_state.py::test_cache_namespace_clear_preserves_durable_agent_os_state`; `tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases[cache]` and `[code-index]`; `tests/test_t05_cache_state_isolation.py::test_scoped_memory_delete_preserves_all_relations_until_authorized`; `tests/test_t05_cache_state_isolation.py::test_sqlite_cache_recovers_corruption_after_first_initialization`; `tests/test_t05_cache_state_isolation.py::test_process_crash_after_cache_rebuild_preserves_durable_agent_state`; `tests/test_t05_cache_state_isolation.py::test_concurrent_derived_recovery_preserves_durable_agent_state[cache]` and `[code-index]`.
- Do not execute until T20 assigns the shared pytest slot. No tests run in this continuation.

## T20 follow-up — dotted trace keys
- Static review found dotted secret-key paths could miss segment-boundary redaction. The owned matcher now treats `.` as a sensitive-key segment separator; the existing trace selector also covers `auth.token` and `credentials.apiKey`.
- AST parse passed for `http_server.py` and `test_debug_trace_request_summary.py`; `git diff --check` clean with existing LF/CRLF warnings. No tests run.
- Latest raw SHA256 supersedes earlier trace hashes: `http_server.py` `6B3CF5F1F055EB3DC6E187750E3D286D0CDCECD22A83E714C0867732FC42C8E3`; `test_debug_trace_request_summary.py` `206EA71255EFDC210345CE08EE6ABD207CD01E50E98A846835C45D049E991B93`.

## T08 memory scope-policy handoff
- Owner-reviewed hunk sent to T08 through T20 for integration; T05 did not edit T08 checkout. Target thread: `01a0d30c-43ad-7f63-83cd-57cb666585d7`.
- Exact file/function: `src/local_ai_hub/agent_memory.py::_context_scope_sql`, T05 current lines 131–192. Public caller: `MemoryStore.find_for_context(root=..., task_id=..., tenant=..., clone_id=..., worktree_id=..., branch=..., include_kinds=..., limit=...)`.
- T05 base: HEAD `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`; base blob `4e6fb2fdbf829c188ebc73081c88e85b90482f6f`. Current whole-file Git blob `7ef714b8e97735cc2e1f0efd4cd84daa7213249f`; current SHA256 `C743109242F8189AFCBAA99F3068861D60E9BBCEE64DFF577433C049C59EA2FE`.
- Contract: GLOBAL stays cross-project; tenant-tagged rows require exact tenant, tenantless GLOBAL rows remain visible. Repository and other scoped rows require exact canonical root and tenant provenance when supplied; missing context sees only tenantless/rootless scoped rows. Tenant label is routing identity, not authentication.
- T08 should call `find_for_context` to retrieve repository and task records together. `find(scope=TASK, ...)` intentionally narrows results to task scope. Context tenant must match row provenance; otherwise scoped result is empty by design.
- Current T05 `agent_memory.py` hash remains unchanged. Four new source-first T05 selectors were added to `tests/test_agent_memory.py` (current SHA256 `E4D05998AE1B2778A22CFFFE51ECB5381996066D760611BE8DB064F2341012F8`); no production hunk changed after handoff. Git reports 29 file-level dirty entries, same count as before. New selectors await T20 slot assignment; no tests were run.
