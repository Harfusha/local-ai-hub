# T05 DB separation fault matrix — 2026-10-01

## Ownership boundary

- `cache.sqlite3` is derived and disposable. `SQLiteCache._recover()` may quarantine it and rebuild its schema; it must not touch `agent_state.sqlite3` or durable leases.
- `agent_state.sqlite3` is durable. Known schema migration takes a verified backup before migration DDL, then applies DDL and data conversion transactionally. Backup or migration failure must leave the original database recoverable.
- Cache clear removes derived cache rows only. Durable task, event, memory, verification, and lease records remain in their owning stores.

## Fault coverage map

| Fault boundary | Existing coverage | Candidate coverage |
| --- | --- | --- |
| Corrupt derived DB recovery | Cache and code-index corruption preserves durable state and leases; initialized cache recovery; restart and concurrent recovery | — |
| Cache rebuild interruption | Process termination after rebuild leaves durable state readable | Inject schema creation failure after quarantine, check durable DB bytes and records, then retry cache creation |
| Known migration backup failure | Backup helper collision, partial-file cleanup, timeout, verification and content checks | Route backup verification failure through migration; prove source DB/sidecar byte identity, owned partial backup cleanup, and retry |
| Migration DDL interruption | Transactional migration success, historical layouts, unknown/unsupported layout fail-closed | Inject DDL failure after initial migration DDL; verify original schema/data restored, verified backup retained, and retry succeeds |
| Cache clear | Scoped namespace clear preserves durable stores | Existing targeted clear coverage remains in `tests/test_t05_cache_clear_durable_state.py` |

## Candidate changes

- `tests/test_t05_agent_state_migrations.py`: migration backup-verification failure and post-backup transactional DDL failure/retry.
- `tests/test_t05_cache_state_isolation.py`: quarantine followed by schema-rebuild failure, byte comparison of durable DB/sidecars, durable record checks, and successful retry.

## Validation status

No tests have been run. T08 released its slot, but T20 assigned the next window to T06; T01 is also still active. T05 execution remains pending an explicit T20 slot assignment after those gates.

Static review only; no source implementation files were changed for this matrix. Workspace root: `C:\Users\Adam\.codex\worktrees\t05-identity-recovery\.local-ai-hub`.

## Root-current fault receipt — 2026-10-01

The scoped combined runner `python -B artifacts/t05-run-root-overlay-acceptance.py` passed **43 tests in 19.59s**. It exercised root migration baseline tests copied byte-for-byte from SHA `E65BD621876ED30F647B1E68C6C6460FF9520457F45A2C48E1FA40C1C67386F2`, plus T05-owned backup-failure and DDL-failure/retry tests in `tests/test_t05_root_migration_faults.py`. Both new fault selectors pass against actual root `agent_events.py` SHA `7BBA75A0A335A1BEF0370F636D65F36477BF0638261723A1778E4DC06BB8B949`.

The cache section covers corruption recovery, failed schema rebuild followed by retry, process-crash recovery, and namespace clear. It excludes only concurrent cross-process derived-cache recovery (T06 boundary). Child worker source paths are explicit and asserted against the root `src` path. Cache worker test patch SHA: `C3966647EA97BD26DED761705BD8393756FC5DC098145EDE40979C718EBD6A84`.

Root-current migration fault-test patch SHA `E9D5C58A6173F8FEE2EE113B36AF4BCA2B9139E8DD8197E43A6A2D795A2AB8F4` passes `git apply --check --whitespace=error`. No root files were written; no T08 migration/lifecycle implementation was changed.
