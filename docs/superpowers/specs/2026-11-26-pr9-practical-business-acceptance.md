# PR #9 Practical Business Acceptance

**Goal:** Verify Git-first Agent OS behavior through realistic repository workflows, not only isolated validators.

**Scope:** Merged PR #9 Git-first project task, memory, incident, legacy migration, SQLite projection rebuild, and exposed CLI/HTTP/MCP surfaces. This acceptance does not claim completion of the broader V4 backlog.

## User scenarios

1. **Project and business task:** Two independent repositories declare separate project identities and publish same-purpose tasks. Contracts retain goal, acceptance criteria, constraints, checkpoints, status, and attempt ancestry. Invalid or stale ancestry is rejected.
2. **Reusable memory:** A developer records a durable project rule, reads it after a clean clone, and sees project boundaries preserved. Session IDs, credentials, private receipts, and secret-like values never enter shared records.
3. **Operational incident:** A repeated failure maps to a stable signature. An incident marked resolved requires a concrete fix; unresolved or vague fixes never appear verified.
4. **Clone and projection lifecycle:** A clean second clone rebuilds projections without importing leases, raw events, credentials, or receipts. Repeated rebuild is idempotent; source updates replace projections; source deletion removes stale projections; separate projects never overwrite one another.
5. **Legacy migration:** Preview is offline, bounded, read-only, snapshot-bound, and paginated. Live attempts and confidential records stay unpublished. A changed snapshot aborts publication; only the reviewed record is published.
6. **Real entrypoints:** Supported CLI, HTTP, and MCP operations expose the same results and authorization boundaries. Read-only modes reject writes; unauthorized callers cannot publish state.

## Pass conditions

- Each scenario is exercised in an isolated temporary repository with a realistic business record and independently checked outcome.
- SQLite is proven disposable and reconstructible from canonical Git state; records are correctly scoped across at least two projects.
- Negative cases fail closed with actionable errors and leave canonical files and unrelated records unchanged.
- Runtime behavior is tested through available product entrypoints; unit tests alone do not satisfy acceptance.
