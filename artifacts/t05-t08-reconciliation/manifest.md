# T05/T08 snapshot patch

Patch SHA-256: `8d3601a6717be82a7d7b75a13d51580f90829e55dd86deaf6785ed9abdde1d8f`

## Expected target snapshot
- Repository HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`
- Dirty `src/local_ai_hub/agent_events.py`: `47b564d268e756abd23dab1d9c51f4f18ffd5bc4ff319b57ece9e4b654d8234d`
- Existing dirty `tests/test_agent_t08_durable_contract.py`: `dc7ed405b9516459b11e04e4d1d58bdbda0210e76ced924e1e930d27637401e2`
- `tests/test_t05_agent_state_migrations.py`: expected absent; patch adds it.

## Scope and validation
Patch changes `agent_events.py`, adjusts T08 backup-failure test seam, and adds T05 migration tests. Scratch integration run: 129 passed. T08 follow-up replay reported 128 passed and one failure in `test_concurrent_legacy_initializers_accept_completed_migration`; that test passed in isolation and the T05 migration file passed standalone (22/22). Order/load stability is not yet proven. `git apply --check` passed (exit 0). T08 worktree was not modified by artifact preparation.

## Migration and storage contract
Schema version is 1. Known legacy layouts are backed up and verified before migration; unknown layouts and versions above 1 fail closed. No v2 migration exists in this patch. Historical migration copies legacy per-event schema versions into `agent_event_schema_versions`; normal appends do not write rows, current source has no reader for this table, and retention does not prune its rows. Therefore sparse historical override/default and cleanup semantics remain undefined and need a separate code change or explicit contract before a v2 schema upgrade.

Cache and durable state use separate SQLite files in the same state directory: `cache.sqlite3` and `agent_state.sqlite3`.