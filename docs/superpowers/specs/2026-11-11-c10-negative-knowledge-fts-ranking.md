# C10: Negative Knowledge FTS Ranking

## Goal

Complete the accepted Round 6 C10 criterion: `IncidentStore.find_negative_knowledge()` must use a bounded SQL candidate query and rank matching incidents by FTS relevance.

## Design

- `agent_incidents` remains canonical. Build a connection-local temporary FTS5 index from the latest eligible incidents in the requested repository for each query.
- Do not add persistent tables, triggers, or columns. AgentStateStore preflight rejects unknown persistent schema objects; cleanup of any existing derived objects is an offline owner task.
- Include operation, error, redacted message, root cause, verified fix, and affected paths in the temporary index. Keep repository, ignored, expiry, and latest-signature filters in SQL while building it.
- Tokenize caller text into safely quoted FTS terms. Rank with BM25, then `updated_at DESC` and incident ID for deterministic ties. Apply the existing candidate cap as a bound SQL parameter and return no more than caller limit.
- Rebuild the temporary index on each call so canonical insert, update, and delete changes are visible immediately. Use bounded recent/lexical fallback only when SQLite lacks FTS5; never report fallback as FTS-verified.

## Acceptance

1. A relevant older incident outranks newer unrelated incidents within the same repository.
2. SQL applies a bound candidate limit after FTS matching; API returns at most caller limit.
3. Canonical updates and deletes affect the next call; no persistent FTS object is created.
4. Results remain repository-scoped, query punctuation is safe, and existing limit validation remains enforced.
5. Focused tests pass. Broad suites remain gated on a stable shared-checkout window.

## Out of scope

No runtime restart, database cleanup, Stability-owned code, public API change, model action, or broad validation run.
