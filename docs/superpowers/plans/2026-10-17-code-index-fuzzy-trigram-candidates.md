# Code-index fuzzy trigram candidate plan

## Scope

Implement the accepted design in `docs/superpowers/specs/2026-10-17-code-index-fuzzy-trigram-candidates.md` inside the isolated `codex/f34-dashboard-health` candidate. Preserve complete fuzzy results and canonical APIs. Do not execute tests, compile, or benchmarks until the complete source bundle is closed.

## Source steps

1. Extend the disposable code-index schema with per-symbol trigram postings and reject an older derived schema through the existing archive-and-rebuild path.
2. Add one helper to replace postings for selected paths from the committed `symbols` rows, within the caller's SQLite transaction. Stream posting writes in bounded chunks.
3. Synchronize postings on single-file updates, batch updates, unindexable/deleted/excluded paths, and prune. Update direct-SQL symbol fixtures that exercise `query` so they maintain derived postings deliberately.
4. For queries whose every term has at least three Unicode code points, materialize the union of symbols containing every distinct trigram of any term in one searchable field. Feed only that complete superset to the existing scorer. Use complete-scope scan for short terms and when posting lookup fails.
5. Add deferred unit regressions comparing indexed and full-scan results, scores, totals, ordering, pagination, Unicode/repeated grams, selective scorer reduction, batch replacement, unindexable/delete, prune, and schema rebuild.
6. Review query planning and write amplification statically. Later, after source-bundle closure, run the full intended validation and a paired pinned-data benchmark before claiming performance improvement.

## Checkpoints

- [x] Design states exact result contract and no-migration policy.
- [x] Source paths and deferred tests implemented; unit tests remain unrun.
- [x] Manual source review and staged `git diff --check` complete. Hub `review_diff` returned a different checkout's files, so it is not counted; indexed impact review remains unavailable for this worktree.
- [ ] Full source bundle closed; then run integrated tests and benchmark.

## Risks to resolve in implementation

- False negatives would corrupt totals and offset pages; candidate generation must be a mathematical superset of every positive scorer branch.
- Every symbol mutation and path deletion must update postings in the same transaction.
- Trigram sets must use Python Unicode `lower()` and distinct overlapping slices.
- Tests and internal fixtures that directly mutate derived tables must also populate postings or deliberately exercise full-scan fallback.
