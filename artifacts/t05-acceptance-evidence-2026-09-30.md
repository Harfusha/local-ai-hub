# T05 acceptance evidence — 2026-09-30

- Worktree: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub`
- HEAD/base: `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`
- Goal: blocked; identity/global memory lifecycle and separation of disposable cache from durable Agent OS state remain in scope.
- No root/master edits. No T06 cross-process invalidation changes. No T08 async recovery changes.

## Ownership

- Existing T05 candidate: `src/local_ai_hub/agent_memory.py` one-line GLOBAL tenant-filter change; `tests/test_agent_memory.py` regression; `tests/test_agent_memory_http_identity.py` endpoint test; isolated delete identity hunk in `src/local_ai_hub/http_server.py`.
- New owned test: `tests/test_t05_cache_clear_durable_state.py` verifies namespace-only cache clear and reopened tasks, events, AgentMemory, verification receipt, and lease.
- Inherited dirty paths: `src/local_ai_hub/agent_events.py`, `src/local_ai_hub/http_server.py` inherited guard/legacy hunks, `src/local_ai_hub/memory.py`, `tests/test_agent_state_transport.py`, `tests/test_audit_round2_enhancements.py`, `tests/test_client_transport.py`, `tests/test_production_readiness_repairs.py`, `tests/test_t05_cache_state_isolation.py`, `tests/test_t05_agent_state_migrations.py`, `tests/test_memory_scope_delete.py`, unrelated artifacts.
- `http_server.py` dirty preimage remains unverified: recorded SHA256 `d7bec2b689c8256260b320b40a46940bd01ba05ddcaaa5805f45c278dce510df`; reconstructed candidate `09d9bf15a36a1447e13acb8c264b349ca16c8affe013f71f3b0d68b468952696`.

## Latest AgentMemory candidate status — 2026-09-30

- Scoped delete now accepts optional tenant and applies tenant provenance within its atomic SQL delete. GLOBAL delete ignores transport tenant. Static review found scope, tenant normalization, and relation cleanup consistent.
- Regression selectors `tests/test_agent_memory.py::test_global_memory_delete_ignores_transport_tenant_but_keeps_scope` and `::test_scoped_memory_delete_requires_matching_tenant` have not run after this candidate. Shared test slot is unassigned; prior suite receipts do not validate these edits.
- HTTP source provenance remains unresolved. No root integration performed.

## Owner-only audit additions — 2026-09-30

- Existing shared-memory contract is workspace-wide last-writer-wins: `tenant` is returned as a label, excluded from `(workspace, memo_key)` primary key, and does not authenticate a private tenant. `BEGIN IMMEDIATE` makes expected-version check and write atomic across processes.
- Static review confirms AgentMemory scoped delete filters tenant provenance atomically; GLOBAL delete ignores tenant after root/repository-scoped lookup. HTTP route rejects non-GLOBAL delete without server-verified project/worktree context. Relations are removed only when matching record row is deleted.
- Derived recovery uses process-local/instance-local locks in `SQLiteCache` and `CodeIndex`; simultaneous recovery can lose disposable derived entries. Durable state uses a distinct `agent_state.sqlite3`. No T08 source changed.
- Added unrun process regressions: `tests/test_identity_contracts.py::test_workspace_memo_expected_version_serializes_across_processes`; `tests/test_t05_cache_state_isolation.py::test_concurrent_derived_recovery_preserves_durable_agent_state[cache]`; same selector with `[code-index]`. They synchronize workers, assert one version-2 winner and one stale conflict, or check derived DB integrity and durable task/memory after concurrent recovery.
- Static checks only: modified tests and embedded worker scripts AST parse; `git diff --check` clean with LF/CRLF notices. No tests run; shared pytest slot waits behind T07/T08.
- Current raw SHA256: `tests/test_identity_contracts.py` `73ec7eec1c12b0f20516f064fba2ec4fb3fec97bc344227daa9dbc6c31cc2eb8`; `tests/test_t05_cache_state_isolation.py` `f6b92a67287b3ec07cfd2b758a1414426ba4b15c4457e04eb65837db5814f333`; see scoped handoff for full source/test hash map and exact selector inventory.

## Current-turn receipts

Commands ran from worktree with `$env:PYTHONPATH='src'`:

- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_identity_contracts.py -k 'not memory_delete_requires_matching_scope_identity'` — `29 passed, 1 skipped, 1 deselected in 5.35s` (symlink privilege skip).
- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_memory_http_validation.py` — `8 passed in 0.37s`.
- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_memory_scope_delete.py` — `3 passed in 11.20s`.
- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_t05_cache_state_isolation.py` — `5 passed in 2.71s`.
- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_t05_agent_state_migrations.py` — `22 passed in 23.56s`.
- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_t05_cache_clear_durable_state.py::test_cache_namespace_clear_preserves_durable_agent_os_state` — `1 passed in 1.17s`.
- `python -m pytest -q --tb=short -p no:cacheprovider tests/test_vision_artifacts.py::test_artifacts_are_tenant_scoped_and_same_content_cannot_overwrite tests/test_vision_artifacts.py::test_artifact_identity_rejects_non_string_tenant_labels tests/test_vision_artifacts.py::test_artifact_list_rejects_falsey_non_string_tenant_labels tests/test_vision_artifacts.py::test_normal_reopen_preserves_hashed_v1_identity_and_isolates_tenants tests/test_vision_artifacts.py::test_binary_integrity_rejects_mismatched_stored_identity` — `12 passed in 0.88s`.
- `git diff --check` — clean; Git reports existing LF-to-CRLF warnings only.

## Prior receipts, not repeated

- Four-selector AgentMemory identity receipt — `4 passed in 9.94s`.
- AgentMemory HTTP identity + inherited scoped-delete guard — `2 passed in 7.01s`.
- Local AI Hub repository/command/coord tools were not exposed in this session; prior context request returned `outcome_unknown` (`req_fa7557f35494`). Tests used one bounded native fallback. No Hub retry.


## AgentMemory regression triage

- Initial non-duplicate module command: `$env:PYTHONPATH='src'; python -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_memory.py -k 'not global_memory_delete_ignores_transport_tenant_but_keeps_scope and not memory_find_enforces_root_repository_and_tenant_identity'` => `22 passed, 2 failed, 2 deselected in 21.62s`.
- Both failures were unchanged base tests querying old `memory:<scope>:<key>` stream IDs. Current recorder uses length-prefixed stream IDs; persisted idempotency events were present under the correct key. Corrected only assertions in `tests/test_agent_memory.py` to query `kind` and `idempotency_key`.
- Red/green selector command: `$env:PYTHONPATH='src'; python -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_memory.py::test_record_idempotency_reuses_existing_record tests/test_agent_memory.py::test_record_idempotency_is_atomic_under_concurrency` => `2 passed in 3.49s` after assertion correction.
- Full filtered module rerun command above => `24 passed, 2 deselected in 21.38s`.
- No production source changed during this regression repair.
- New evidence test file SHA256: `0c03c90e075d45ebce1fd44d9a78d3c4337bf3d4f6fc2457742428a87b3888a3.
- Updated test_agent_memory.py SHA256: `26150f1e1e387e015aa57351d2c3e61c4b0e63e878e15321ea6f854ee92fa5b9`.


## Fresh completion-audit receipts — 2026-09-30

All commands used `$env:PYTHONPATH='src'; python -m pytest -q --tb=short -p no:cacheprovider` from the assigned worktree. The prior four-pass receipt selector was excluded.

- `tests/test_identity_contracts.py -k 'not memory_delete_requires_matching_scope_identity'` — `29 passed, 1 skipped, 1 deselected in 4.77s`; Windows symlink privilege skip remains.
- `tests/test_memory_http_validation.py` — `8 passed in 0.23s`.
- `tests/test_memory_scope_delete.py` — `3 passed in 4.65s`.
- `tests/test_agent_memory.py -k 'not global_memory_delete_ignores_transport_tenant_but_keeps_scope and not memory_find_enforces_root_repository_and_tenant_identity'` — `24 passed, 2 deselected in 19.38s`.
- `tests/test_t05_cache_state_isolation.py` — `5 passed in 3.08s`.
- `tests/test_t05_agent_state_migrations.py` — `22 passed in 14.62s`.
- `tests/test_t05_cache_clear_durable_state.py::test_cache_namespace_clear_preserves_durable_agent_os_state` — `1 passed in 0.93s`.
- The five targeted artifact identity/migration selectors listed above — `12 passed in 1.42s`.
- `git diff --check` — clean; existing line-ending warnings only.

- Fresh HTTP candidate verification after completion audit: `$env:PYTHONPATH='src'; python -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_memory_http_identity.py::test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope` — `1 passed in 7.85s`.


## Resumed-goal full-suite audit

- Full T05-and-lifecycle command including inherited `tests/test_t05_agent_state_migrations.py` and two targeted transport selectors completed with `138 passed, 1 skipped, 1 failed in 80.59s`. The single failure was `tests/test_t05_agent_state_migrations.py::test_concurrent_legacy_initializers_accept_completed_migration`, raising `RuntimeError: agent_state changed during schema preflight` from inherited `agent_events.py`.
- Focused rerun of that concurrency selector passed (`1 passed in 0.77s`); earlier isolated migration-file receipt was `22 passed`. The behavior is schedule-sensitive.
- The master plan assigns `agent_events.py` schema preflight/migration and durable DB recovery to T08. No T08 source was changed.
- Full in-scope T05 suite excluding that T08 migration module, with AgentMemory, identity contracts, memory HTTP validation, vision artifacts, AgentMemory HTTP, shared memory delete, cache-state/reopen, cache-clear, and scoped transport tests: `117 passed, 1 skipped in 50.21s`.


## Provenance recovery and isolated handoff

- Exact recorded preimage SHA256 searched in T05 artifacts. Only evidence/manifest references found; no preimage snapshot stored there.
- Checked 129 all-ref `http_server.py` history versions plus reflog commits (165 unique commit snapshots total) by hashing raw Git blob bytes. No match for recorded SHA256.
- Enumerated 16,668 Git objects; checked 151 blob objects within 20 KB of current `http_server.py` size. No hash match. This bounded size filter does not cover differently sized blobs. A full unreachable-object `git fsck` scan exceeded 60 seconds and was stopped.
- Created `artifacts/t05-agent-memory-core.patch`, SHA256 `be595039667d74674ad55313aaab36c2f866c4f6f864d7ec77201cf68a8b0940`. Patch contains only `agent_memory.py` and `test_agent_memory.py`; reverse `git apply --check` passed. It excludes mixed `http_server.py` hunk and HTTP endpoint test, so it is a reviewable core identity candidate, not full endpoint acceptance.
- Existing in-scope T05 suite excluding T08 migration module remains `117 passed, 1 skipped`; Windows symlink privilege caused skip. T08 migration concurrency selector separately passed when rerun; inherited source remains untouched.
- T05 goal remains blocked in goal state because mixed HTTP preimage provenance is unavailable. No root/master integration performed.


## Root overlap audit

- Read-only root worktree check: `C:\Users\Adam\.local-ai-hub`, HEAD `824c9eb99dfd6baca5a7cf0e43d94f0e33dd4b11`.
- Root HEAD lacks T05 GLOBAL tenant-filter condition and candidate regression. Root dirty `agent_memory.py` already contains equivalent condition; root dirty `test_agent_memory.py` has a simpler GLOBAL delete regression. Both paths have unrelated dirty hunks, so no patch applied.
- Root dirty `http_server.py` already contains identity-filtered memory lookup and scoped delete logic. Its dirty provenance remains unverified; no changes made.
- Root and assigned copies of `tests/test_t05_cache_state_isolation.py` have the same normalized Git blob OID `defa1197cbe35237ea97d3cf3cf01573f0d0681c`; raw SHA256 differs from line endings. Cache patch does not apply cleanly to current root copy. At this earlier check, HTTP identity and cache-clear tests were absent; cache-clear test was added later as recorded below.
- Core patch therefore overlaps existing dirty root files and is not safe to apply blindly. Root was inspected only; no root/master file changed.


## Cache-clear receipt reconciliation

- Later root update supersedes earlier absence note: root now contains `tests/test_t05_cache_clear_durable_state.py`, SHA256 `7178ba62817a5abc21e5173f109e1bcd6645ff7362c47eacf488d116a71880db`. Orchestrator reports its exact selector passed (`1 passed in 0.79s`) after assertion changed to receipt ID and passed-state persistence.
- Aligned assigned-worktree copy's final assertion to the same persistence contract; no duplicate test added. Assigned test SHA256 `7178ba62817a5abc21e5173f109e1bcd6645ff7362c47eacf488d116a71880db`. Fresh exact selector: `1 passed in 3.26s`.
- Root selector receipt is orchestrator-reported; assigned-worktree selector was run here. Root production sources and mixed HTTP hunk remain untouched.


## Final preimage hash check

- Current root `http_server.py` SHA256: `d311b7c34f694864e0d4b4b316db656bdd643b5b36de58642f4e9c3411840cf0`.
- Current assigned-worktree `http_server.py` SHA256: `684f0362c667289d2b3e08bcf193c0c5a70d80aeb9735808f83ba876d0d05925`.
- Neither current file matches recorded dirty preimage SHA256 `d7bec2b689c8256260b320b40a46940bd01ba05ddcaaa5805f45c278dce510df`. Mixed HTTP hunk remains unattributed; no edits made.


## Tenant-bearing GLOBAL delete evidence

- Existing focused endpoint test already covers tenant-bearing GLOBAL delete: `tests/test_agent_memory_http_identity.py:102-117`. It sends tenant `codex`, rejects wrong root with 404 while retaining record, then deletes through matching root/repository identity and confirms record absence. No duplicate test added.
- Fresh receipt already recorded above: `test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope` => `1 passed in 7.85s`.
- `MemoryStore.delete` accepts explicit scope/scope_id only. HTTP route validates full identity through `get` before delete; this test proves transport tenant does not block GLOBAL delete and root boundary remains enforced. It exercises current worktree HTTP hunk; unknown preimage still blocks attribution/integration.


## Final scoped-suite receipt after cache-clear assertion correction

- Exact command: `$env:PYTHONPATH='src'; python -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_memory.py tests/test_identity_contracts.py tests/test_memory_http_validation.py tests/test_vision_artifacts.py tests/test_agent_memory_http_identity.py tests/test_memory_scope_delete.py tests/test_t05_cache_state_isolation.py tests/test_t05_cache_clear_durable_state.py::test_cache_namespace_clear_preserves_durable_agent_os_state tests/test_agent_state_transport.py::test_http_memory_get_is_scope_and_root_isolated tests/test_agent_state_transport.py::test_http_memory_delete_requires_verified_worktree_scope`.
- Result: `117 passed, 1 skipped in 52.58s`. Skip remains Windows symlink privilege (`WinError 1314`). Suite includes focused tenant-bearing GLOBAL HTTP delete and updated durable receipt assertion.
- Final `git diff --check`: clean; line-ending warnings only.
- Scoped apply-check details and base/current blob IDs: `artifacts/t05-scoped-handoff-2026-09-30.md`.


## Physical SQLite separation proof

- `test_derived_sqlite_recovery_preserves_agent_state_and_leases` runs for `cache.sqlite3` and `code-index.sqlite3`. Both paths are asserted distinct from `agent_state.sqlite3`; each derived DB is corrupted and recovered, then tasks, events, AgentMemory, receipt row, and lease are read after reopen. Durable DB remains present without a corruption quarantine. The final scoped suite includes these cases: `117 passed, 1 skipped in 52.58s`.
- T05/T08 boundary preserved: no `agent_events.py` edits; migration/data-preservation tests remain intact. Migration module: `22 passed`; concurrent schema-preflight test passed in isolation after one full-suite timing failure.


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
- Added atomic root/repository identity predicates to memory DELETE and route forwarding. Added a regression that reassigns provenance between lookup and delete; test is authored but unrun.
- Expanded debug trace redaction for compound and camelCase secret keys with test inputs for `client_secret`, `clientSecret`, `X-LocalAI-Token`, and `x-api-key`; test is authored but unrun.
- Static checks: Python AST parse passed for the four edited source/test files listed in scoped handoff; `git diff --check` clean with line-ending warnings. No pytest executed because shared test slot remains unavailable. Earlier `117 passed, 1 skipped` is historical and does not validate these latest edits.
- Current file SHA256 values are recorded in `t05-scoped-handoff-2026-09-30.md`. The mixed dirty `http_server.py` preimage remains unverified, so whole-file extraction/integration remains blocked.

## T20 slot handoff
- No pytest run. Targeted selectors and line-level hunk ownership are recorded in `t05-scoped-handoff-2026-09-30.md`.
- In `http_server.py`, this continuation owns only the trace-redaction changes at lines 425 and 687-688 plus root/repository argument forwarding at lines 2604-2609. Earlier T05 identity-handler code and the legacy `/api/memory/delete` hunks predate this continuation. Whole-file preimage remains unavailable; preserve all inherited and unclassified hunks.
- Wait for T20 shared slot assignment before executing the listed selectors. T05 remains incomplete until those tests run and pass.

## T20 live matrix receipt — 2026-09-30
- Candidate HEAD: `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`; no commit or integration made.
- Current worktree SHA256: `src/local_ai_hub/agent_memory.py` `B79D06DFC2A0FD4085C5825C8C923FBE187762B250E8741F6040F6CBCD28E341`; `src/local_ai_hub/http_server.py` `49EBEF7CC1AFB2C523AE064F1CA601E9937E3EF397C4E85239A92B4E63E6C420`; `tests/test_agent_memory.py` `7393CAE5206916EB6D3B527F3C7BF226E4690156BD36ABB1C9F9CC40B894C202`; `tests/test_agent_memory_http_identity.py` `4E037BDAABE47F3386009D43669CD861ECC9A37F6522CBDFE9C837F1402B544F`; `tests/test_debug_trace_request_summary.py` `792114950F68F6A8C002ED53AA5E24A8D4D4890580F00D57F1AFFEE3F57D10D5`; `tests/test_identity_contracts.py` `73EC7EEC1C12B0F20516F064FBA2EC4FB3FEC97BC344227DAA9DBC6C31CC2EB8`; `tests/test_memory_scope_delete.py` `5E84A8116A5FB98C8E10488D63DC6E74993F86050AA4B3310DCE24801D3CCB69`; `tests/test_t05_cache_state_isolation.py` `F6B92A67287B3EC07CFD2B758A1414426BA4B15C4457E04EB65837DB5814F333`; `tests/test_t05_cache_clear_durable_state.py` `7178BA62817A5ABC21E5173F109E1BCD6645FF7362C47EACF488D116A71880DB`. `tests/test_t05_agent_state_migrations.py` is inherited/unowned here; current SHA256 `51042B19DC7FEA19DE928D0505ABB95453DBEFE730AC96EE51E37CA28EE96F86`.
- Latest prepared migration selector: `tests/test_t05_agent_state_migrations.py` (whole module; 15 named tests, parameterization yields the recorded 22 cases). Cache selectors: `test_cache_namespace_clear_preserves_durable_agent_os_state`; `test_derived_sqlite_recovery_preserves_agent_state_and_leases[cache]` and `[code-index]`; `test_scoped_memory_delete_preserves_all_relations_until_authorized`; `test_sqlite_cache_recovers_corruption_after_first_initialization`; `test_process_crash_after_cache_rebuild_preserves_durable_agent_state`; `test_concurrent_derived_recovery_preserves_durable_agent_state[cache]` and `[code-index]`. Auth selectors are enumerated exactly in the scoped handoff under “Focused T05 identity/trust selectors,” plus the owned HTTP identity and trace-redaction selectors above.
- Existing evidence artifact records historical receipts: migration module `22 passed`; cache state isolation `5 passed` (before the two concurrent-recovery cases were added); cache clear `1 passed`; identity contracts filtered run `29 passed, 1 skipped, 1 deselected`; scoped memory delete `3 passed`; AgentMemory identity `4 passed`; HTTP identity plus inherited guard `2 passed`. These are prior command summaries in this Markdown artifact, not current raw logs; no raw pytest log file is attached. They do not verify the new concurrent subprocess tests, the root/repository reassignment DELETE regression, or expanded secret-key redaction.
- Unresolved: Workspace memos are intentionally shared by `(workspace, memo_key)`; tenant is provenance/label, not authorization. Cross-process CAS and concurrent cache-recovery selectors remain unrun. Cache and code-index recovery locks are process/instance-local and may lose disposable derived entries under races; current regressions preserve durable `agent_state.sqlite3` but do not require derived entries to survive. Scoped HTTP memory delete remains denied without server-verified project/worktree identity. GLOBAL tenant is deliberately ignored; supplied root/repository identity is rechecked atomically on delete.
- Test-slot status: no explicit T20 handoff received in this thread; prior direction says other owners hold the shared slot. No tests run for this receipt. Keep T05 open.

## T20 follow-up — dotted trace keys
- Redaction matcher now treats dot as a sensitive-key segment separator. Added `auth.token` and `credentials.apiKey` cases to the existing owned trace selector. No test run; selector remains pending owner slot.
- AST parse passed for both edited Python files; `git diff --check` clean with existing LF/CRLF warnings.
- Superseding hashes: `src/local_ai_hub/http_server.py` `6B3CF5F1F055EB3DC6E187750E3D286D0CDCECD22A83E714C0867732FC42C8E3`; `tests/test_debug_trace_request_summary.py` `206EA71255EFDC210345CE08EE6ABD207CD01E50E98A846835C45D049E991B93`.

## Source-only regression adequacy review
- HTTP race selector is a real `LocalAIHTTPServer` plus `urllib` POST. Its `get` wrapper reassigns stored root/repository provenance after the route lookup returns and before DELETE executes; expected outcome is 404 and the row remains addressable through the new identity. It restores provenance before the ordinary success-delete assertion.
- Trace selector invokes the exact sanitizer helper used by the HTTP debug request capture call at `http_server.py:2016`. It asserts compound, camelCase, hyphenated, and dotted sensitive keys redact while safe nested text remains. No HTTP-level trace-store round trip is asserted.
- Workspace memo CAS selector starts two independent `sys.executable` subprocesses; ready marker files plus a release barrier hold both before expected-version 1 writes. Expected: both exit 0, exactly one success at version 2, one version conflict, and final value is the winner.
- Derived recovery selector starts two independent subprocesses behind the same barrier against corrupted cache or code-index SQLite. Both must exit 0, final derived DB `quick_check` is `ok`, and durable task/memory reopen. It intentionally does not promise derived cache entries survive concurrent rebuild.
- Static receipt after dotted-key edits: AST parse printed `AST OK src/local_ai_hub/http_server.py` and `AST OK tests/test_debug_trace_request_summary.py`; `git diff --check` emitted only existing LF-to-CRLF warnings. No pytest executed.

## T05 source-only handoff checkpoint
- Candidate HEAD remains `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`. Exact current owner-path SHA256 inventory is above; `http_server.py` is mixed dirty and only named own hunks are attributable. Original dirty preimage SHA is unavailable.
- Expanded AST command parsed these nine paths without imports: `agent_memory.py`, `http_server.py`, `test_agent_memory.py`, `test_agent_memory_http_identity.py`, `test_debug_trace_request_summary.py`, `test_identity_contracts.py`, `test_memory_scope_delete.py`, `test_t05_cache_state_isolation.py`, `test_t05_cache_clear_durable_state.py`. Output: one `AST OK <path>` for each. Embedded process scripts also parsed: `write_script` once and `recovery_script` twice, all `EMBEDDED AST OK`.
- `git diff --check`: no whitespace errors; Git printed only existing LF-to-CRLF notices for `agent_memory.py`, `test_client_transport.py`, `test_identity_contracts.py`, and `test_t05_cache_state_isolation.py`.
- Remaining acceptance gap: execute the exact auth/trace, cross-process, migration, and cache selectors listed in scoped handoff after T20 slot assignment; current historic receipts predate new concurrent and dotted-key regressions. Trace test exercises the sanitizing helper; source call-site is confirmed at `http_server.py:2016`, but persisted trace-store roundtrip is not directly asserted. Decide from T05 criteria whether a store-level HTTP assertion is required.
- No tests run. No non-owned source or test path touched; `agent_events.py`, legacy handler hunks, and `/api/context/pack` remain outside current edits.

## AgentMemory context isolation receipt — 2026-09-30
- Scope policy: `GLOBAL` is intentionally cross-project, but a row with tenant provenance is returned only to that exact tenant; without tenant context, only tenantless globals are visible. Non-GLOBAL repository rows require canonical root and exact tenant provenance when a tenant is supplied; task/session/clone/worktree/branch rows require exact scope ID and exact root/tenant provenance when those contexts are supplied. Missing tenant context sees only tenantless scoped rows. Tenant labels are routing identity, not authentication.
- `find_for_context` returns only ACTIVE/CONFIRMED unexpired rows. SQL excludes invalid JSON value/evidence/provenance shape and nonnumeric record timestamps; per-row decoding errors and malformed evidence/provenance are skipped without mutation. No automatic repair or quarantine occurs during reads. `IncidentStore.find_negative_knowledge` remains excluded until it has scoped provenance/query API.
- Newly authored in this memory-scope pass: `agent_memory.py` `_context_scope_sql` and `find_for_context` scope/provenance/validity hunks; `tests/test_agent_memory.py::test_find_for_context_enforces_repository_tenant_and_task_identity` and `::test_find_for_context_excludes_stale_expired_and_corrupt_rows`. Pre-existing dirty hunks in these files include AgentMemory `find`/`delete` identity changes, scoped delete tests, and idempotency assertion corrections; no other file edited for this subtask.
- Current SHA256: `src/local_ai_hub/agent_memory.py` `C743109242F8189AFCBAA99F3068861D60E9BBCEE64DFF577433C049C59EA2FE`; `tests/test_agent_memory.py` `E482034FDF19FF795EDBDB52B5DE272D0B64F79D9CDDEF5EC8965C0FCE783410`.
- Focused command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_memory.py::test_memory_find_enforces_root_repository_and_tenant_identity tests/test_agent_memory.py::test_find_for_context_enforces_repository_tenant_and_task_identity tests/test_agent_memory.py::test_find_for_context_excludes_stale_expired_and_corrupt_rows` — `3 passed in 1.83s`, exit 0, shell duration 2.461s; log `artifacts/t05-agent-memory-focused-final-2026-09-30.log`, SHA256 `08DC152B2C54B83F736DCF765393EB70C31BB6CA91BDA71E4A1D95A09E9196D7`.
- Full AgentMemory command: `python -B -m pytest -q --tb=short -p no:cacheprovider tests/test_agent_memory.py` — `29 passed in 20.62s`, exit 0, shell duration 21.116s; log `artifacts/t05-agent-memory-full-2026-09-30.log`, SHA256 `E250D979527C455930DE6D2A1BB3D6B11E88D78319B9270DE0F2CACF67C53AA5`.
- Triage receipts retained: focused attempt 1 `1 failed, 2 passed` (tenantless global omitted; log `t05-agent-memory-focused-2026-09-30.log`, SHA256 `C293D687387FAB6892348062CF5BBDC03EC272BF19E0A03E0A52DCCCC5F1B879`); attempt 2 `3 passed` but exit 1 for unclosed SQLite connection (log `t05-agent-memory-focused-retry-2026-09-30.log`, SHA256 `99C4CD3D2073A08DB99E5855C371391798B69E495FF91CBBBF19A289F15D6148`). Fixed tenantless-global predicate and used `closing()` in test; final focused and module receipts above are green.
- Slot was explicitly assigned by T20, used only for these three selectors and one module run, then released to T08. Other T05 acceptance selectors remain unrun. `git diff --check` has no whitespace errors; only existing LF-to-CRLF warnings.

## T05 AgentMemory selectors — 2026-09-30
- Fixed source candidate on HEAD `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`, worktree `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub`.
- Final command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_memory.py::test_find_filters_global_and_repository_rows_by_tenant_and_root tests/test_agent_memory.py::test_find_skips_corrupt_rows_without_aborting_scoped_read tests/test_agent_memory.py::test_memory_write_redacts_private_fields_and_blocks_sensitive_records tests/test_agent_memory.py::test_memory_correction_lineage_and_delete_survive_reopen` — `4 passed in 1.44s`, shell elapsed `1.995 s`, exit `0`.
- Receipt: `artifacts/t05-memory-policy-four-selectors-green-2026-09-30-rerun.log`, SHA256 `1B7DDE289C6406883AA6C9B12DB1DFA6F00306160C58EFC8E4464948CA077C56`.
- First attempt was `3 passed, 1 failed` because the added clean-read assertions followed the test's deliberate sensitivity mutation; moved those assertions before the mutation and reran only the same four selectors.
- Static checks on final production/test source: Python AST parse passed; `git diff --check` exit 0 with LF-to-CRLF notice. No broader tests run.
- Current path hashes: `src/local_ai_hub/agent_memory.py` `ADC4889AE9FE456CC245B5202C7E0D6CD0D897F56C3503C47B7CEEED9E797463`; `tests/test_agent_memory.py` `70CF1471E242DEB19E05F8E2838A6DF0E8E719C154D477A4BF27C3586957759E`.
- T05 releases its exclusive T20 shared-test-slot assignment after this receipt.

## Final T05 handoff — 2026-09-30
- Verified slice only: `agent_memory.py` tenant/root-scoped find/get, corrupt-row skip, persisted memory sanitization/sensitivity rejection, and correction lineage/delete-on-reopen; exact four-selector receipt above. No claim for full T05 completion.
- This slice is logically separable as its own AgentMemory policy/test patch. `agent_memory.py` and `tests/test_agent_memory.py` are mixed dirty files containing earlier T05 candidate hunks; extract by hunks, never by transplanting either whole file. `http_server.py` is also mixed, with unresolved original dirty preimage; preserve its own/inherited hunks.
- Still open for whole T05: scoped/global delete and HTTP identity selectors; workspace memo sharing/CAS and cross-process races; lease/artifact identity; AgentMemory concurrency; cache/code-index recovery, crash and durable-state preservation; migration selectors; debug trace redaction. Exact selectors are in `artifacts/t05-scoped-handoff-2026-09-30.md` under “Exact pending selectors”. Prior 29-pass module receipt is historical and predates this source candidate. T06 invalidation and T08 async recovery remain separate ownership.
- Current shared dirty inventory includes T08 `src/local_ai_hub/agent_events.py`; mixed T05/inherited `src/local_ai_hub/http_server.py`; inherited `src/local_ai_hub/memory.py`, `tests/test_agent_state_transport.py`, `tests/test_audit_round2_enhancements.py`, `tests/test_client_transport.py`, `tests/test_production_readiness_repairs.py`, `tests/test_t05_cache_state_isolation.py`, `tests/test_t05_agent_state_migrations.py`, `tests/test_memory_scope_delete.py`; other T05 candidate hunks in `tests/test_identity_contracts.py`, `tests/test_debug_trace_request_summary.py`, `tests/test_agent_memory_http_identity.py`, and `tests/test_t05_cache_clear_durable_state.py` remain outside this four-selector receipt.
- `/api/context/pack` was not changed. T20 has been sent the final receipt and T05 releases its slot; no further test runs requested.
