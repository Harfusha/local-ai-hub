# PR #9 Practical Business Acceptance

**Goal:** Verify Git-first Agent OS behavior through realistic repository workflows, not only isolated validators.

**Scope:** Merged PR #9 Git-first project task, memory, incident, legacy migration, SQLite projection rebuild, and exposed CLI/HTTP/MCP surfaces. This acceptance does not claim completion of the broader V4 backlog.

## User scenarios

1. **Project and business task:** Two independent repositories declare separate project identities and publish same-purpose tasks. Contracts retain goal, acceptance criteria, constraints, checkpoints, status, and attempt ancestry. Invalid or stale ancestry is rejected.
2. **Reusable memory:** A developer records a durable project rule, reads it after a clean clone, and sees project boundaries preserved. Session IDs, credentials, private receipts, and secret-like values never enter shared records.
3. **Operational incident:** A repeated failure maps to a stable signature. An incident marked resolved requires a concrete fix; unresolved or vague fixes never appear verified.
4. **Clone and projection lifecycle:** A clean second clone rebuilds projections without importing leases, raw events, credentials, or receipts. Repeated rebuild is idempotent; source updates replace projections; source deletion removes stale projections; separate projects never overwrite one another.
5. **One-time update migration:** The updater imports only portable records attributable to the current stable project identity. Migration is bounded, snapshot-bound, restartable, and idempotent. Live attempts, private receipts, confidential records, and records from other projects stay local. Normal runtime exposes no legacy migration reader or writer.
6. **Real entrypoints:** Supported CLI, HTTP, and MCP operations expose the same results and authorization boundaries. Read-only modes reject writes; unauthorized callers cannot publish state.

## Pass conditions

- Each scenario is exercised in an isolated temporary repository with a realistic business record and independently checked outcome.
- SQLite is proven disposable and reconstructible from canonical Git state; records are correctly scoped across at least two projects.
- Negative cases fail closed with actionable errors and leave canonical files and unrelated records unchanged.
- Runtime behavior is tested through available product entrypoints; unit tests alone do not satisfy acceptance.

## User clarification: checkout portability, concurrent agents, and migration cutover

The accepted implementation must also satisfy these repository-wide requirements:

1. **Checkout portability:** The stable project identity comes from the canonical project manifest, not an absolute checkout path, branch name, or worktree path. Existing clones and linked worktrees of the same project load the same canonical Git records. Checkout, switch, pull, merge, rebase, and reset invalidate the affected local projection and fence work started against the previous snapshot. Worktree paths remain local execution metadata and never become portable ownership identity.
2. **Multiple agents:** Agents in one checkout use bounded local leases and revision-checked atomic writes; concurrent updates to the same record conflict explicitly, while independent records can proceed. Agents in disconnected clones do not receive a fabricated global lock. Their claims are advisory; after Git synchronization, competing attempts require deterministic conflict handling and re-review. Private leases, receipts, and runtime attempts stay local.
3. **One-time update migration:** The updater performs one bounded, restartable, idempotent migration from the prior SQLite authority into canonical Git records. It validates a stable source snapshot, preserves a recoverable backup until cutover succeeds, and records a durable completion marker. After successful cutover, normal runtime has no legacy readers, writers, fallback paths, dual writes, manual legacy batch commands, or compatibility shims. Migration code may run only as the explicit updater migration.
4. **Required practical acceptance:** Use real Git repositories to test repeated path relocation, two linked worktrees, two independent clones with distinct local state directories, branch checkout while work is in flight, same-record stale-writer conflicts, disjoint concurrent records, competing offline claims, interrupted/restarted migration, and rejection of legacy runtime entrypoints after cutover. Verify canonical records survive and private runtime state does not cross checkout boundaries.
