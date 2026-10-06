# T05 manual master synchronization

Owner: sole T05 writer. Workspace: `C:/Users/Adam/.codex/worktrees/t05-identity-recovery/.local-ai-hub`.
No Hub calls (parent reported terminal unavailable; native fallback explicitly authorized).
No writes to root/other worktree, installation, PATH changes, stash, reset, clean, push, or master-ref updates.
Token-economizer bounded slices used; requested `ensure-tools.ps1 -PlanOnly` failed because script is absent. No installation attempted.

## Pins and preservation

- Original detached HEAD: `43f7b1ccb57762a8fa581b14f4aeeac84b520ed4`.
- Initial pin merged: `614a6a50ac2a3e4106270136cb8e584e770c3752` (object verified as commit).
- Initially observed master: `fbc965f568105e1a8d3dc03ae4c9da5531a9617e`; subsequent master movement is handled by one separately pinned final merge.
- Branch: `codex/sync-t05-20261006`.
- Durable checkpoint: `df9850131a79191c5a860a1d231d3acd867869db`.
- Backup ref: `refs/heads/codex/backup-t05-pre-sync-20261006`.
- `original-inventory.json`: exact pre-merge porcelain status, all 16 tracked dirty paths and 399 untracked paths, size/SHA256, original HEAD, observed master, relevant paths and collisions.
- `original-bytes.zip`: exact bytes of all 16 tracked dirty files and all 13 relevant new tests, original tracked binary diff and staged binary diff. Raw bytes avoid Git line-ending normalization ambiguity.
- Seven untracked/master collisions were committed into the checkpoint before merge: agent memory context tenant isolation, HTTP identity, memory delete identity contract, T05 state migrations, cache clear durable state, delete artifacts, FTS atomicity test modules.
- All 386 unrelated original untracked artifacts remain in place. `preservation-receipt.json` verifies every original unrelated hash and every archived raw source/test hash; contains exact original/current per-path hashes and remaining original-untracked porcelain entries. It excludes stale intermediate merge status.
- Runtime databases/cache created by tests remain uncommitted under ignored audit test directories. No original runtime state was removed or staged.

## Semantic conflict decisions and superseded hunks

Every superseded original hunk remains recoverable through the checkpoint ref and raw archive. `resolve.py` records the initial per-hunk choices; later surgical reconciliation is represented in Git history/diff.

| Path | Final decision / concrete supersession |
| --- | --- |
| `docs/SECURITY_MODEL.md` | Keep newer transport/header tenant description; shared workspace memo generation explanation remains once. Supersede duplicate older memo paragraph in conflict. |
| `src/local_ai_hub/agent_events.py` | Keep master cursor tables, append transaction/publication locking, supported incident/task/outbox schema fingerprints, unversioned-current migration handling and busy retry exceptions. Older strict schema-version-only classifier and standalone append body superseded by these newer mechanisms. Remove duplicate import. |
| `src/local_ai_hub/agent_memory.py` | Keep master transactional delete/quarantine, tombstone replay rejection, complete identity aliases and tenant-agnostic GLOBAL deletion. Preserve T05 safe serialization, malformed projection filtering, SQL JSON/type filters, atomic promotion event/projection helper, unqualified get restriction, explicit quarantine scope arguments. Older stricter blanket TASK/SESSION/REPOSITORY predicates and duplicate tenant SQL superseded by master's newer root/repository identity rules; qualified GLOBAL lookup uses master behavior. |
| `src/local_ai_hub/agent_tasks.py` | Keep master public memory bindings, scoped task identity, contract-aware context snapshot, audit history and resume refresh in one transition. Remove older duplicate setter/snapshot and unreachable second resume update, which would override bindings or bypass newer memory audit lifecycle. |
| `src/local_ai_hub/http_server.py` | Keep newer project resolver, header/query identity precedence, explicit delete identity and tenant-agnostic GLOBAL delete. Older blanket scoped-delete 403 replaced by master's checked identity aliases. Preserve T05 composed-key debug redaction, memo delete scope validation/forwarding, verified mutation identity helper and quarantine response; use resolved identity for promote/quarantine while preserving master's authenticated approval gate. `/api/context/pack` AST matches initial master pin exactly; no redesign. |
| `src/local_ai_hub/memory.py` | Retain T05 explicit global/tenant memo delete scope; tenant scope requires tenant, global clears filter. No superseded functionality. |
| `tests/test_agent_memory.py` | Merge newer temporary-root and scoped identity fixtures; retain missing original top-level tests/helpers by name, including cursor/write rollback and stricter identity tests. Deduplicate auto-merged provenance keyword. Same-name older fixture/assertion variants remain in checkpoint. Some old stricter identity expectations remain failing, explicitly unaccepted. |
| `tests/test_agent_memory_context_tenant_isolation.py` | Retain T05 projection helper and tenantless adversarial fixture coverage; merge public record-path fixtures. Tenantless-only-GLOBAL expectation retained as failing evidence rather than changing newer master context behavior. |
| `tests/test_agent_memory_http_identity.py` | Merge master's GLOBAL transport semantics/trusted promotion fixtures; retain independent original tests and MemoryStatus import. Older expected successful caller-forged user promotion superseded by explicit 403 assertion. Replay test now expects tombstone ValueError, retaining no-resurrection checks. Other same-name old assertions saved in checkpoint. |
| `tests/test_audit_round2_enhancements.py` | Use matching master `session-cascade` fixture/delete scope; older `session-audit` naming is equivalent and preserved in checkpoint. |
| `tests/test_client_transport.py` | Retain master's new invalid-object response test alongside original fixture additions. |
| `tests/test_identity_contracts.py` | Combine master subprocess output tracking/CREATE_NO_WINDOW with original independent worktree idempotency/delete tests. |
| `tests/test_production_readiness_repairs.py` | Keep explicit master root/repository delete identity; original incomplete delete fixture superseded. |
| `tests/test_t05_agent_state_migrations.py` | Keep master artifact-backed verification receipt fixture and added accepted incident-layout tests. Retain original projection/provenance assertions and missing-identity rejection. Older receipt fixture lacking required artifact evidence superseded. |
| `tests/test_t05_cache_clear_durable_state.py` | Retain original explicit task/root/tenant identity fixture and negative unqualified lookup; no removed original cases. |
| `tests/test_t05_cache_state_isolation.py` | Retain original stronger provenance, denied cross-tenant cases, cache recovery failure case and worker loaded-source-origin assertions; no original test removed. |
| `tests/test_t05_memory_delete_artifacts.py` | Combine master public record/event setup with original three-table deletion fault injection and reopened-state assertions. Seed marker sequence now 2 (public record already emits sequence 1). Original silent replay-return expectation superseded by master tombstone ValueError; no-resurrection checks remain. |
| `tests/test_t05_memory_fts_atomicity.py` | Retain original full event equality rollback check, add master cursor lookup. Original and current record/update cases retained. |
| `tests/test_vision_artifacts.py` | Keep master explicit `action="get"` matching current MCP schema; older omitted action superseded. |

Other original tracked paths (`evidence.py`, agent state operations/transport, debug trace summary, evidence contract) merge without conflicts; relevant root snapshot/adoption/delete scope test modules committed intact or mechanically integrated. Gemini CodeGraph removal and master context implementation inherited; no CodeGraph resurrection.

## Validation / acceptance

Targeted validation only; no release suite. Commands use assigned source via PYTHONPATH, PYTHONDONTWRITEBYTECODE=1, no pytest cache, and a unique audit-local basetemp.

1. Initial 11-module pytest collection: failed on auto-merged repeated `provenance` keyword; repaired.
2. Intermediate 11-module run: 122 passed, 14 failed, 1 skipped in 68.84s. Three sequence fixture failures, two silent replay expectations and caller-forged promotion expectation reconciled with current master afterward. Source changed during this intermediate run; this is diagnostic evidence, not final-source acceptance.
3. Preservation/compile check: all 29 raw backups verified, all 386 unrelated original artifacts unchanged; zero Python syntax errors; context pack AST equal to initial pin.

## Final snapshot and handoff

- Initial merge commit: `c275990ad51b656ce52ccf16456610363d187b89`.
- Final snapshot master pin merged exactly once: `9b794d7fa24abb179a17d87e14becdfa7fc8cd50` (read-only snapshot, no tracking of further master movement).
- This final snapshot contains `fbc965f568105e1a8d3dc03ae4c9da5531a9617e` (verified ancestry), including the user's requested T03 test commit and subsequent already-published integrations.
- Final snapshot merge has no conflicts. Final receipt is refreshed after committing the merge; its `integration_merge_head` identifies that merge. A following audit-only receipt commit completes the handoff.
- Incremental review patches: `incremental-vs-initial-master.patch` and `incremental-vs-final-master.patch` (source/test/doc changes; self-generated audit payload excluded). Git's full diff also includes the committed audit/checkpoint materials.
- Final targeted runtime suite NOT rerun: user explicitly directed no acceptance chase and committed handoff despite failures. Intermediate diagnostic result remains **122 passed, 14 failed, 1 skipped**; later merge/fixture adjustments are syntax/preservation checked only, not claimed runtime accepted.
- Unaccepted diagnostic cases: newer context allows tenantless same-root records while older T05 tests expect exclusion; newer scoped lookup allows specific legacy TASK provenance cases; GLOBAL deletion ignores transport tenant; original HTTP/global fixtures mix older transport assumptions. Final source also retains snapshot/adoption tests not included in the 11-module diagnostic command. These require separately owned acceptance review; no new feature work added here.
- Reconciled fixture issues after that run: duplicate provenance removed; deletion marker expects sequence 2 after public record; record replay expects ValueError after tombstone; HTTP payload `approver=user` expects 403 under trusted actor policy; qualified GLOBAL get no longer rejects already-matched provenance wholesale.
- Remaining original artifacts: 386 untracked files, hashes unchanged; tracked source/task/test/docs committed. New pytest runtime artifacts stay ignored/uncommitted inside assigned worktree. Exact paths and hashes are receipt-backed.
- Commit records reconciled unfinished work; it does not assert feature acceptance. No full release suite, publication, push, or master-ref mutation.

Diagnostic command (run 1 used pytest-run1; run 2 used pytest-run2):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python -m pytest -q --tb=short -p no:cacheprovider --basetemp=artifacts/sync-t05-20261006/pytest-run2 tests/test_agent_memory.py tests/test_t05_agent_state_migrations.py tests/test_t05_memory_delete_artifacts.py tests/test_t05_memory_fts_atomicity.py tests/test_identity_contracts.py tests/test_memory_scope_delete.py tests/test_memory_delete_identity_contract.py tests/test_agent_memory_context_tenant_isolation.py tests/test_t05_cache_clear_durable_state.py tests/test_t05_cache_state_isolation.py tests/test_agent_memory_http_identity.py
python artifacts/sync-t05-20261006/preservation.py
```

Failed diagnostic node IDs: `test_agent_memory.py::{test_find_for_context_enforces_repository_tenant_and_task_identity,test_task_lookup_rejects_rootless_and_tenantless_memory,test_find_for_context_session_memory_requires_session_and_tenant,test_get_global_requires_unowned_or_matching_tenant}`; `test_t05_memory_delete_artifacts.py::{test_replaying_record_after_delete_does_not_restore_memory_or_fts,test_delete_cleanup_failure_rolls_back_memory_and_search_state[agent_entity_relations],test_delete_cleanup_failure_rolls_back_memory_and_search_state[agent_memory_embeddings],test_delete_cleanup_failure_rolls_back_memory_and_search_state[agent_memory_fts]}`; `test_agent_memory_context_tenant_isolation.py::test_find_for_context_without_tenant_returns_only_tenantless_global`; `test_agent_memory_http_identity.py::{test_http_global_memory_identity_ignores_transport_tenant_but_keeps_scope,test_http_memory_get_and_mutations_bind_transport_tenant_and_project_identity,test_http_memory_public_identity_blocks_spoofed_origin_and_foreign_queries,test_http_unscoped_global_get_promote_and_delete,test_http_unscoped_global_delete_then_record_replay_keeps_tombstone}`.

Skipped diagnostic node: `test_identity_contracts.py::test_workspace_memo_migration_*` symlink variant, Windows privilege 1314; no privilege workaround attempted.
