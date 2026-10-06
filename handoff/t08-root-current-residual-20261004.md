# T08 root-current residual diagnosis

Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
`agent_tasks.py` before T08 production patch: `5ce57d0ef0b7a17992f604ab67390e481702b0f51393c375102623475fcf280a`; integrated result: `599812f8cd345ffa0087581cae60e073ae34c6914a344efd989baa937e3a1b0c`. Parent reports root T08 set **33 passed in 4.01s**.
Root was not edited by this residual diagnosis.

## Residual patches

### T08 test contract

Patch: `handoff/t08-root-current-test-contracts-20261004.patch`
SHA-256: `0a68270c514a62a05b7c190bf94858bafdaf1461f3653557423aa34785de833e`.
Root `git apply --check --whitespace=error`: PASS. Three T08 test paths only:
- `test_agent_t08_crash_after_commit.py`: use dict keys for event kind/sequence.
- `test_agent_t08_event_page_snapshot.py`: use dict sequence keys.
- `test_agent_t08_cache_isolation.py`: verify exact persisted task-memory DB row/value; avoid unscoped retrieval.

`event_page()` declares `dict[str, Any]`, materializes events with `event.to_dict()`, HTTP consumers use dict `.get()` and serialize the page. The four object-attribute failures are stale T08 expectations, not a production return-type regression. Root event page source SHA: `1b8e63a5ff329090801cd7f19e7df7a95e42ac0034465ac5fa06d566b279ccf4`.

T05 fail-closed memory rules explain two cache-memory failures: tests call `MemoryStore.get(task_record_id)` without identity. Default `get()` searches GLOBAL only; TASK lookup requires task, root, and tenant. Test data has none of those provenance identity fields. Cache rebuild does not explain it. T08 patch checks `agent_memory_records` by `record_id`, `scope=task`, `scope_id=task_id`, then decoded value. No `agent_memory.py` change. T05 coordination permission is pending.

Root test preimages: crash-after-commit `9c949a0cb2d9fc5f58fa7264ef1e8f5def13bb657328998591d0a97918849e8f`; event-page snapshot `32a481ed12f35d309a53e6a2203ffb278837ff6e71e432cff5ac5d582b74ed66`; cache isolation `c132ef4f7ca3ebd6fd072b10c4ac5835501ec6660d23d62f95690697561e8e75`.

Focused receipts in isolated root-current copy, patches applied there only:
- Three event recovery/order parameterizations plus snapshot selector: **4 passed in 0.85s**.
- Cache isolation file after DB-row assertion correction: **2 passed in 0.83s**.

### Incident migration allowlist production defect

Patch: `handoff/t08-root-current-incident-schema-allowlist-20261004.patch`
SHA-256: `403a2b3543943d13c19205f5ba336bd9a0b2823de4daade5556fbb95af25dcd5`.
Root `git apply --check --whitespace=error`: PASS; not applied. Root preimage `agent_events.py` SHA `1b8e63a5ff329090801cd7f19e7df7a95e42ac0034465ac5fa06d566b279ccf4`.

Root `_ALTERNATE_OBJECT_SQL_HASHES` contains the same `agent_incidents` key twice. Python keeps the second tuple and silently discards the first tuple’s `43c461…` and `b3f8fa…` legacy hashes. The migration test’s expected set matches candidate’s single non-duplicated allowlist. This is a production migration defect, not stale test. Residual hunk removes shadowing duplicate; keeps existing allowlisted layouts. Table schema overlaps T05 ownership; get T05 review before integration. Isolated migration selector after hunk: **1 passed in 0.25s**.

## Overall receipts and limits

Before residual patches, root/current-copy T08-adjacent set was **40 passed, 7 failed in 12.01s**. Re-running same seven failures with unpatched root `agent_tasks.py` gave **7 failed in 8.21s**, confirming they were not caused by that task-writer patch. Failure categories: two unscoped task-memory reads, four dict-vs-object event-page assertions, one duplicate-key migration allowlist defect.

Full T08 suite has not been rerun after residual patches; parent requested that after T05 reconciliation. Isolated validation copy remains at `handoff/.validation-root-current-20261004`. Candidate source files remain unchanged. No T05 message sent pending user authorization.

## Durable database split evidence

The application already separates paths: `src/local_ai_hub/app.py` creates `AgentStateStore(state_dir / "agent_state.sqlite3")`; command caches in `src/local_ai_hub/commands.py` use `state_dir / "cache.sqlite3"`; CodeIndex uses `code-index.sqlite3`. `SQLiteCache._recover()` quarantines only `self.path` plus that file's `-wal`/`-shm`, then recreates derived schema. T05 test `test_derived_sqlite_recovery_preserves_agent_state_and_leases` asserts different resolved paths, corrupts cache or code-index, reopens durable task/event/memory/receipt/lease stores, and checks durable rows. This supplies split/fault evidence; no runtime path change justified.

T05 owns `tests/test_t05_agent_state_migrations.py`, including backup verification failure with source-byte preservation/retry, DDL failure rollback/retry, unsupported version/layout/object fail-closed, WAL/SHM preservation, destination reservation/cleanup, concurrent initialization, backup timeout, and exact schema fingerprint changes. T08 will consume T05's fresh owner receipts after its active reconciliation; no duplicate migration matrix or `sqlite_support.py` edits.

T05 coordination status at last read: T05 holds temporary review lease for `agent_incidents.py`/`sqlite_support.py`, no edits; their root context lookup remains in progress. T08 migration hunk is in `agent_events.py`, file-disjoint from that lease but semantically overlaps incident schema allowlisting. Keep root integration and full-suite rerun pending T05's review/reconciliation.
