# T08 durable memory tombstone receipt — 2026-10-01

Scope: root-current `src/local_ai_hub/agent_memory.py` tombstone/replay guard and `tests/test_agent_memory_t08_tombstones.py`. T20 applied the patch to the shared root tree; T08 did not run other selectors.

- Root HEAD: `98a9a1a7611af574caf20a88620c4aa3eb2e918a`
- Patch: `t08-memory-deletion-tombstone-root-current.patch`; SHA-256 `E550267FAF9E3281B487C19FA513A4AFA48CDA13472F2DCBCF4C91F492EA2A41`
- Root source SHA-256: `F6680A399A731E6CF40E79F19F4BC113B9EE72734F2FC48424D937292363CABE`
- Root test SHA-256: `3A4B570D7FA765F5F583609B6BB243325B73FA808AF2DB7690A3F17E848388ED`
- Root `git apply --check`: passed before integration.
- Sequential scratch apply: T08 patch then T05 projection-cleanup patch passed.
- Static AST parsing: patched source and test passed.
- Authorized root selector: `python -B -m pytest -q -p no:cacheprovider tests/test_agent_memory_t08_tombstones.py::test_deleted_memory_record_replay_is_tombstoned_after_reopen --tb=short` — **1 passed in 0.29s**.

Behavior: deletion and minimal `memory.deleted` event commit atomically and publish through the ordered event-publication seam. Replay checks tombstones by stable record ID across streams, including changed-scope attempts, before restoring a missing projection. Event payload contains only the record ID. T05 owns embedding/FTS cleanup; its patch applies after T08 in a scratch copy. No broader T08/T05 suite was run.
