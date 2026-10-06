# T08 root-compatible task publication patch

Owner scope: `src/local_ai_hub/agent_tasks.py` only. Root not edited.
Root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`.
Root working preimage SHA-256: `5ce57d0ef0b7a17992f604ab67390e481702b0f51393c375102623475fcf280a`.
Candidate source SHA-256 unchanged: `a86ff3b368c18eccead725cf30ed4bf793489324e209fe4a7ebf38820665c7ca`.

Patch: `handoff/t08-root-compatible-agent-tasks-20261004.patch`
Patch SHA-256: `b63c61157581c4f754a28528fd4e5fa56839c13c6906fcb3210d28b56c2cccd7`.
Patch stat: one file, 8 hunks, 41 insertions, 44 deletions. Root `git apply --check --whitespace=error`: PASS, exit 0; not applied. Hunk preimages match root working file.

## Delta

Adds `_run_ordered_task_write`: opens one `isolation_level=None` SQLite connection; enters `ordered_event_publication(con)` before callback; retries callback on that connection; publishes after callback returns; closes connection in `finally`. Routes `_commit_create`, `_commit_update`, and `add_verification_receipt` through it. Each callback keeps its `BEGIN IMMEDIATE`, `COMMIT`, `ROLLBACK`, and `append_in_transaction(con, ...)` ownership on that same connection. CAS SQL, search-index transaction, idempotency checks and timeout values remain. Replay returns no event. No test or T09 path changed; `tests/test_agent_receipt_completion_t09.py` is disjoint.

## Receipts

Validation used isolated copy of current root source/tests under `handoff/.validation-root-current-20261004`; patch applied only there.

Before-patch RED: integration owner reported all three create/update/receipt parameterizations fail at `publication_calls == [True]`.

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_live_order.py::test_task_event_commits_share_append_publish_order_lock`

Patched result: **3 passed in 1.80s**.

`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_agent_t08_cache_isolation.py tests/test_agent_t08_crash_after_commit.py tests/test_agent_t08_durable_contract.py tests/test_agent_t08_event_page_snapshot.py tests/test_agent_t08_live_order.py tests/test_agent_t08_migration_recovery.py tests/test_agent_t08_receipt_transaction.py tests/test_agent_incident_scope.py tests/test_lease_atomic_deadlock.py`

Patched result: **40 passed, 7 failed in 12.01s**. Same seven failing selectors with unpatched root `agent_tasks.py`: **7 failed in 8.21s**. Existing unrelated integration drift: two cache-memory recovery assertions; four event-page tests expect `AgentEvent` objects while root returns dicts; migration test expects two obsolete schema hashes. No added failure from this patch.

Root source SHA remained `5ce57d0e…fcf280a`; patch remains unapplied. Candidate source unchanged.
