# T08 Durable State Split and Residual Acceptance Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Work in T08 candidate only. Do not edit root or `src/local_ai_hub/agent_memory.py`.

**Goal:** Close T08 residual durability receipts against current root contracts and hand off only owner-compatible patches.

**Architecture:** Durable agent records live in `agent_state.sqlite3`; command/query caches are rebuildable derived state in `cache.sqlite3` and `code-index.sqlite3`. AgentStateStore owns durable schema preflight, verified backups, and migrations. SQLiteCache may quarantine and rebuild only its derived path. Reuse T05-owned migration and memory-identity evidence; T08 changes its own tests and event contract only.

**Tech Stack:** Python, SQLite, pytest.

**Scope:** Root-current T08 acceptance continuation; T05 memory/migration coordination; no root writes.

## Tasks

- [x] **1. Verify storage path separation and owner boundaries.** Root `app.py` constructs AgentStateStore at `state_dir / "agent_state.sqlite3"`; CommandBroker caches use `state_dir / "cache.sqlite3"`; CodeIndex uses `code-index.sqlite3`. Existing `tests/test_t05_cache_state_isolation.py::test_derived_sqlite_recovery_preserves_agent_state_and_leases` verifies distinct paths and reopens task, event, memory, receipt, lease stores after derived-file corruption. Keep this T05 test as owner evidence; add no duplicate source change.

- [x] **2. Prepare T08 contract test patch.** Root-current patch `handoff/t08-root-current-test-contracts-20261004.patch` updates event-page assertions from object attributes to dict keys and replaces identity-less task-memory reads with an exact `agent_memory_records` row/value check. It changes only `tests/test_agent_t08_{crash_after_commit,event_page_snapshot,cache_isolation}.py`. Root `git apply --check --whitespace=error` must pass.

- [x] **3. Diagnose incident schema allowlist.** Root `agent_events.py` defines duplicate `_ALTERNATE_OBJECT_SQL_HASHES[('table','agent_incidents','agent_incidents')]` keys. Python keeps the later one-hash tuple, dropping two supported legacy hashes from the earlier tuple. Keep fix as separate patch `handoff/t08-root-current-incident-schema-allowlist-20261004.patch`; require T05 ownership review before root integration.

- [ ] **4. Finish T05 coordination.** Reconcile the cache-test DB-row assertion with T05 fail-closed identity contract. Do not change `agent_memory.py`; reuse T05's cache path isolation and verified migration/fault-matrix receipts. Request direct user authorization before sending cross-task messages.

- [ ] **5. Run focused owner regressions after T05 reconciliation.** Run exact T08 publication, event-page, cache isolation, and incident migration selectors in the isolated root-current copy. Preserve command, root/candidate preimage SHA, patch SHA, result, and duration in `handoff/t08-root-current-residual-20261004.md`.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_live_order.py::test_task_event_commits_share_append_publish_order_lock
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_commit_before_publish_recovers_event tests/test_agent_t08_crash_after_commit.py::test_process_exit_after_task_commit_before_publish_recovers_projection_and_cursor tests/test_agent_t08_event_page_snapshot.py::test_event_page_through_seq_excludes_events_appended_between_pages
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_cache_isolation.py
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_migration_recovery.py::test_legacy_incident_schema_is_allowlisted_and_preserved_on_migration
```

- [ ] **6. Run full T08 owner suite after T05 reconciliation.** Use isolated root-current copy with final owner patches. Separate baseline integration drift from regressions; never claim full acceptance from focused selectors alone.

```powershell
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_cache_isolation.py tests/test_agent_t08_crash_after_commit.py tests/test_agent_t08_durable_contract.py tests/test_agent_t08_event_page_snapshot.py tests/test_agent_t08_live_order.py tests/test_agent_t08_migration_recovery.py tests/test_agent_t08_receipt_transaction.py tests/test_agent_incident_scope.py tests/test_lease_atomic_deadlock.py
```

## Review Focus

- `cache.sqlite3` corruption must quarantine/rebuild only derived DB; durable task/event/memory/receipt/lease rows remain in `agent_state.sqlite3`.
- Durable schema migration must back up and verify before mutation, preserve source bytes on backup/preflight/DDL failure, and allow retry after injected backup/DDL faults. T05 owns `tests/test_t05_agent_state_migrations.py`; reuse its receipts after T05 confirms latest preimages.
- Event-page public shape stays `dict[str, Any]` with event dictionaries; don't revert source to satisfy stale object assertions.
- Memory reads stay fail-closed; don't weaken scope/tenant/root identity to satisfy a test.
- Legacy incident schema allowlist must retain all known hashes without duplicate-key shadowing; T05 confirms table-layout ownership before integration.

## Assigned-worktree owner receipt — 2026-10-04

The full nine-file T08 owner suite passed in the assigned worktree: `52 passed in 19.65s`, HEAD `2b33602adef0d030fea66cdcc04ca742c60b2e32`. Exact command and per-file SHA-256 values are in [the assigned-worktree receipt](../../handoff/t08-assigned-worktree-suite-receipt-20261004.md). The root-current overlay suite and T05-owned memory identity/migration fault-matrix reconciliation remain separate pending gates; this result does not close them.

## Acceptance continuation — 2026-10-04

- Candidate dirty inventory matched recorded inherited state (85 rows); no source/test edits in this continuation.
- Combined T08 owner acceptance: `67 passed in 17.37s`, `-W error::ResourceWarning`.
- Event/task crash recovery selectors: `8 passed in 1.15s`, including process-exit rollback, restart after committed writes, checkpoint, completion and failure.
- Exact commands and contract boundary are in [the continuation receipt](../../handoff/t08-assigned-worktree-suite-receipt-20261004.md). Root remains untested; T05 identity/migration reconciliation remains pending.
