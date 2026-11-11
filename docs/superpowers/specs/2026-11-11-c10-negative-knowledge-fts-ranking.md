# C10: Negative Knowledge FTS Ranking

## Goal

Complete the accepted Round 6 C10 criterion: `IncidentStore.find_negative_knowledge()` must use a bounded SQL candidate query and rank matching incidents by FTS relevance.

## Design

- `agent_incidents` remains canonical. Add a derived FTS5 external-content index over operation, error, redacted message, root cause, verified fix, and affected paths.
- Keep the index synchronized through insert, update, and delete triggers. Rebuild it from canonical rows during the store's one-time schema initialization; do not alter or discard incident rows.
- Keep repository, ignored, expiration, and latest-signature filters in SQL. Join FTS candidates only to the latest record within the requested repository.
- Tokenize user query terms into safely quoted FTS terms. Rank with BM25, then `updated_at DESC` and incident ID for deterministic ties. Keep the existing bounded candidate cap as a bound parameter, and return no more than the caller's validated `limit`.
- Preserve a bounded recent/lexical fallback only when the SQLite build lacks FTS5; do not report that fallback as FTS-verified behavior.

## Acceptance

1. A relevant older incident outranks newer unrelated incidents within the same repository.
2. The SQL query uses a bound candidate limit and the API returns at most `limit` items.
3. Capture, resolve/update, and deletion keep the derived index current; rebuilding restores it from existing rows.
4. Results remain repository-scoped, query punctuation is safe, and current limit validation remains enforced.
5. Focused tests pass. Broad suites remain gated on the stable shared-checkout window.

## Out of scope

No runtime restart, database cleanup, Stability-owned code, public API change, model action, or broad validation run.
