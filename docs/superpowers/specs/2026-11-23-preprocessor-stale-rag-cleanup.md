# Bounded stale RAG reference cleanup

## Problem

The preprocessor currently invalidates every stale path from one RAG batch in a
single SQLite write transaction. A live run exceeded the existing five second
write budget by more than a minute (`elapsed_ms=60661`) and left the project
preprocessing state in `error`. The missing-reference cleanup path already uses
small write batches because its FTS cleanup has similar costs.

## Requirements

- Process stale paths in conservative batches of eight, with one bounded write
  transaction per batch.
- Keep the existing compare-and-swap guard on `(root, path, content_hash)` so an
  older RAG batch cannot invalidate a newer file generation.
- Remove `source_index` rows only for the matching stale hash. Remove FTS rows
  only when no current `source_index` row remains for that path.
- If a batch still exceeds the transaction budget, roll it back and surface the
  error; do not weaken the five second guard or silently accept partial work in
  that batch.
- Cover multi-path cleanup and current-generation preservation with a focused
  regression test.

## Acceptance

1. Seventeen stale paths are cleaned in batches of `8`, `8`, and `1`.
2. Stale metadata, source index rows, and FTS rows are cleared without removing
   a newer file generation.
3. The focused preprocessing test module passes.
